import { fetchAlerts, fetchHealth, fetchSpectrum, fetchSpectrumSites, fetchStats, subscribeToAlerts } from "./api";
import { AlertFeedView } from "./views/alerts";
import { renderHealthTable } from "./views/health";
import { renderSpectrum } from "./views/spectrum";
import { renderStats } from "./views/stats";

const POLL_INTERVAL_MS = 5000;

function byId<T extends HTMLElement>(id: string): T {
  const el = document.getElementById(id);
  if (!el) throw new Error(`missing #${id}`);
  return el as T;
}

function setConnectionStatus(connected: boolean): void {
  const el = byId<HTMLDivElement>("connection-status");
  el.textContent = connected ? "live" : "reconnecting…";
  el.className = `status ${connected ? "status-live" : "status-reconnecting"}`;
}

async function refreshHealth(): Promise<void> {
  const tbody = byId<HTMLTableSectionElement>("rf-health").querySelector("tbody");
  if (!tbody) return;
  try {
    renderHealthTable(tbody, await fetchHealth());
  } catch (err) {
    console.error("failed to refresh health", err);
  }
}

async function refreshStats(): Promise<void> {
  try {
    renderStats(byId("stats"), await fetchStats());
  } catch (err) {
    console.error("failed to refresh stats", err);
  }
}

let currentSpectrumSite: string | null = null;

async function refreshSpectrumSiteList(): Promise<void> {
  const select = byId<HTMLSelectElement>("spectrum-site-select");
  try {
    const sites = await fetchSpectrumSites();
    const previousSelection = select.value;
    select.innerHTML = sites.map((site) => `<option value="${site}">${site}</option>`).join("");
    if (sites.includes(previousSelection)) {
      select.value = previousSelection;
    }
    currentSpectrumSite = select.value || sites[0] || null;
  } catch (err) {
    console.error("failed to list spectrum sites", err);
  }
}

async function refreshSpectrum(): Promise<void> {
  if (!currentSpectrumSite) return;
  const canvas = byId<HTMLCanvasElement>("spectrum-canvas");
  try {
    renderSpectrum(canvas, await fetchSpectrum(currentSpectrumSite));
  } catch (err) {
    console.error("failed to refresh spectrum", err);
  }
}

async function main(): Promise<void> {
  const alertsView = new AlertFeedView(byId<HTMLUListElement>("alerts"));

  try {
    alertsView.setInitial(await fetchAlerts());
  } catch (err) {
    console.error("failed to load initial alerts", err);
  }

  subscribeToAlerts(
    (alert) => alertsView.upsert(alert),
    (connected) => setConnectionStatus(connected),
  );

  byId<HTMLSelectElement>("spectrum-site-select").addEventListener("change", (event) => {
    currentSpectrumSite = (event.target as HTMLSelectElement).value;
    void refreshSpectrum();
  });

  await refreshSpectrumSiteList();
  await Promise.all([refreshHealth(), refreshStats(), refreshSpectrum()]);

  setInterval(refreshHealth, POLL_INTERVAL_MS);
  setInterval(refreshStats, POLL_INTERVAL_MS);
  setInterval(refreshSpectrum, POLL_INTERVAL_MS);
  setInterval(refreshSpectrumSiteList, POLL_INTERVAL_MS * 6);
}

void main();
