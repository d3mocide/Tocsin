import {
  fetchAlerts,
  fetchDispatches,
  fetchHealth,
  fetchHealthHistory,
  fetchReference,
  fetchServices,
  fetchSpectrum,
  fetchSpectrumSites,
  fetchStats,
  fetchStreams,
  fetchSystem,
  fetchTranscripts,
  subscribeToEvents,
} from "./api";
import { byId, el, replaceChildren } from "./dom";
import { isActive, tierOf } from "./format";
import { ALL_TOPICS, healthKey, Store, type Topic } from "./store";
import { renderActivity } from "./views/activity";
import { AlertFeedView } from "./views/alerts";
import { mountFilters } from "./views/filters";
import { renderHealth } from "./views/health";
import { MapView } from "./views/map";
import { WaterfallView } from "./views/spectrum";
import { StationsView } from "./views/stations";
import { renderStats } from "./views/stats";
import { renderConnection, renderDispatchSummary, renderModeChip, renderServices } from "./views/status";
import { StreamsView } from "./views/streams";
import { renderDashboardLiveTranscripts, renderTranscripts } from "./views/transcripts";

// What still polls, and why. Alerts, health, transcripts, and dispatches
// arrive over SSE now and are not polled at all. These three have no push
// feed to ride on: spectrum is a Redis snapshot key sdr_rx overwrites in
// place, and services/streams are point-in-time reads of heartbeat keys
// and Icecast's status page.
const SPECTRUM_POLL_MS = 1000;
const SERVICES_POLL_MS = 10_000;
const STREAMS_POLL_MS = 15_000;
const SITES_POLL_MS = 30_000;
const STATS_POLL_MS = 30_000;
// Relative timestamps ("2m ago") and the active/expired split are both
// derived from the clock, so the page has to repaint on a timer even when
// no data changes -- otherwise an expired warning keeps claiming to
// expire "in 2 minutes" indefinitely.
const CLOCK_TICK_MS = 15_000;

const store = new Store();

function poll(fn: () => void, intervalMs: number): void {
  fn();
  setInterval(fn, intervalMs);
}

function initNavigationTabs(mapView: MapView): void {
  const dashBtn = byId("tab-btn-dashboard");
  const logsBtn = byId("tab-btn-logs");
  const dashView = byId("tab-view-dashboard");
  const logsView = byId("tab-view-logs");

  dashBtn.addEventListener("click", () => {
    dashBtn.classList.add("active");
    logsBtn.classList.remove("active");
    dashView.classList.add("active");
    logsView.classList.remove("active");
    mapView.invalidateSize();
  });

  logsBtn.addEventListener("click", () => {
    logsBtn.classList.add("active");
    dashBtn.classList.remove("active");
    logsView.classList.add("active");
    dashView.classList.remove("active");
  });
}

async function main(): Promise<void> {
  initPanelCollapsing();

  const alertsView = new AlertFeedView(byId("alerts"), store);
  const waterfall = new WaterfallView(byId<HTMLCanvasElement>("spectrum-canvas"));
  const streamsView = new StreamsView(byId("streams"), store);
  const stationsView = new StationsView(byId("nwr-stations"), store);
  const mapView = new MapView(byId("map-view-container"), store);
  const refreshFilterSites = mountFilters(byId("filters"), store);

  initNavigationTabs(mapView);

  // Each panel repaints only when something it actually reads changed.
  // `clock` is in the list for every panel showing a relative time, and
  // is the only reason most of them repaint on a quiet system.
  const render = (changed: ReadonlySet<Topic>) => {
    const touched = (...topics: Topic[]) => topics.some((topic) => changed.has(topic));
    if (touched("system")) renderModeChip(byId("mode-chip"), store);
    if (touched("system")) stationsView.render();
    if (touched("system", "alerts")) mapView.render();
    if (touched("connection")) renderConnection(byId("connection-status"), store);
    if (touched("stats")) renderStats(byId("stats"), store);
    if (touched("services", "clock")) renderServices(byId("services"), store);
    if (touched("stats")) renderDispatchSummary(byId("dispatch"), store);
    if (touched("health", "clock")) renderHealth(byId("rf-health"), store);
    if (touched("streams", "system")) streamsView.render();
    if (touched("activity", "clock")) {
      renderDashboardLiveTranscripts(byId("dashboard-live-transcripts"), store);
      renderTranscripts(byId("transcripts"), store);
    }
    if (touched("activity", "alerts", "system", "clock")) renderActivity(byId("activity"), store);
    if (touched("alerts", "filters", "system", "clock")) alertsView.render();
    if (touched("alerts")) refreshFilterSites();
    if (touched("alerts", "clock")) updateDocumentTitle();
  };
  const renderAll = () => render(new Set(ALL_TOPICS));
  store.subscribe(render);

  const siteSelect = byId<HTMLSelectElement>("spectrum-site-select");
  siteSelect.addEventListener("change", () => {
    store.update("spectrum", (state) => {
      state.spectrumSite = siteSelect.value || null;
    });
    // The waterfall's history belongs to one site; carrying it across a
    // switch would splice two different receivers into one image.
    waterfall.clear();
    void refreshSpectrum();
  });

  // Reference data first and awaited: county names and tier badges are
  // needed to render an alert correctly, and a feed that paints raw FIPS
  // codes for a moment and then reflows is worse than one that waits.
  await store.load("system", fetchReference, (reference, state) => {
    state.reference = reference;
  });

  await Promise.all([
    store.load("system", fetchSystem, (system, state) => {
      state.system = system;
    }),
    store.load("alerts", () => fetchAlerts(200), (alerts, state) => {
      for (const alert of alerts) state.alerts.set(alert.id, alert);
    }),
    store.load("health", fetchHealth, (samples, state) => {
      for (const sample of samples) state.health.set(healthKey(sample.site, sample.channel), sample);
    }),
    // Seeds the sparklines from stored history so a freshly opened tab
    // shows an hour of trend immediately. Without this the trend column
    // stays blank until enough live SSE samples have accumulated, which
    // is the opposite of useful -- the moment you open this page is
    // exactly when you want to know what the last hour looked like.
    store.load("health", () => fetchHealthHistory(3600, 60), (points, state) => {
      for (const point of points) {
        const key = healthKey(point.site, point.channel);
        const series = state.healthHistory.get(key) ?? [];
        series.push(point.rms);
        state.healthHistory.set(key, series);
      }
    }),
    store.load("activity", () => fetchTranscripts(100), (transcripts, state) => {
      state.transcripts = transcripts;
    }),
    store.load("activity", () => fetchDispatches(100), (dispatches, state) => {
      state.dispatches = dispatches;
    }),
  ]);

  subscribeToEvents({
    onAlert: (alert) => store.upsertAlert(alert),
    onHealth: (sample) => store.applyHealth(sample),
    onTranscript: (transcript) => store.prependTranscript(transcript),
    onDispatch: (dispatch) => store.prependDispatch(dispatch),
    onStatusChange: (connected) =>
      store.update("connection", (state) => {
        state.connected = connected;
      }),
  });

  poll(() => void refreshSpectrumSites(), SITES_POLL_MS);
  poll(() => void refreshSpectrum(), SPECTRUM_POLL_MS);
  poll(
    () =>
      void store.load("services", fetchServices, (services, state) => {
        state.services = services;
      }),
    SERVICES_POLL_MS,
  );
  poll(
    () =>
      void store.load("streams", fetchStreams, (streams, state) => {
        state.streams = streams;
      }),
    STREAMS_POLL_MS,
  );
  poll(
    () =>
      void store.load("stats", fetchStats, (stats, state) => {
        state.stats = stats;
      }),
    STATS_POLL_MS,
  );
  setInterval(() => store.notify("clock"), CLOCK_TICK_MS);

  renderAll();

  async function refreshSpectrumSites(): Promise<void> {
    await store.load("spectrum", fetchSpectrumSites, (sites, state) => {
      state.spectrumSites = sites;
      if (!state.spectrumSite || !sites.includes(state.spectrumSite)) {
        state.spectrumSite = sites[0] ?? null;
      }
    });
    const { spectrumSites, spectrumSite } = store.state;
    const current = siteSelect.value;
    if (spectrumSites.join(" ") !== [...siteSelect.options].map((o) => o.value).join(" ")) {
      replaceChildren(siteSelect, ...spectrumSites.map((site) => el("option", { text: site, attrs: { value: site } })));
    }
    siteSelect.value = spectrumSite ?? current;
  }

  async function refreshSpectrum(): Promise<void> {
    const site = store.state.spectrumSite;
    if (!site) {
      waterfall.push(null);
      return;
    }
    await store.load("spectrum", () => fetchSpectrum(site), (snapshot, state) => {
      state.spectrum = snapshot;
    });
    waterfall.push(store.state.spectrum);
  }
}

/** An active Tier A alert in the tab title, so a backgrounded tab still
 * says something is wrong. Tier A is the set that reaches the mesh
 * immediately (design doc §4) -- the same threshold the feed uses for its
 * loudest treatment. */
function updateDocumentTitle(): void {
  const now = new Date();
  const urgent = [...store.state.alerts.values()].filter(
    (alert) => isActive(alert, now) && tierOf(alert, store.state.reference) === "A",
  );
  document.title = urgent.length > 0 ? `(${urgent.length}) ⚠ Tocsin` : "Tocsin";
}

function initPanelCollapsing(): void {
  const STORAGE_KEY = "tocsin_collapsed_panels";
  const rawStorage = localStorage.getItem(STORAGE_KEY);
  let collapsedSet: Set<string>;

  if (rawStorage !== null) {
    try {
      collapsedSet = new Set(JSON.parse(rawStorage));
    } catch {
      collapsedSet = new Set();
    }
  } else {
    // Default collapsed panels on first launch to keep dashboard focused on alerts
    collapsedSet = new Set(["activity"]);
  }

  document.querySelectorAll<HTMLElement>("section.panel").forEach((panel) => {
    const head = panel.querySelector<HTMLElement>(".panel-head");
    if (!head) return;

    const heading = head.querySelector("h2");
    const panelKey = (heading?.textContent ?? "").trim().toLowerCase().replace(/\s+/g, "_");

    const isCollapsed = collapsedSet.has(panelKey);
    if (isCollapsed) panel.classList.add("panel-collapsed");

    const btn = el("button", {
      class: "panel-collapse-btn",
      text: isCollapsed ? "+" : "−",
      attrs: { type: "button", title: "Collapse/expand panel", "aria-label": "Toggle panel collapse" },
    });


    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const nowCollapsed = panel.classList.toggle("panel-collapsed");
      btn.textContent = nowCollapsed ? "+" : "−";
      if (nowCollapsed) {
        collapsedSet.add(panelKey);
      } else {
        collapsedSet.delete(panelKey);
      }
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify([...collapsedSet]));
      } catch {
        // Storage un-writeable
      }
    });

    head.append(btn);
  });
}

void main();

