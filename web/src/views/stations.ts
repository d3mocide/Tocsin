import { el, replaceChildren } from "../dom";
import type { Store } from "../store";
import type { NwrStation } from "../types";

const PAGE_SIZE = 3; // 3 columns x 1 row -- see style.css's .station-grid

export class StationsView {
  private readonly container: HTMLElement;
  private readonly store: Store;
  private page = 0;
  private maxRadiusMiles = 100;

  constructor(container: HTMLElement, store: Store) {
    this.container = container;
    this.store = store;
  }

  render(): void {
    const stations = this.store.state.reference?.stations ?? {};
    const entries = Object.entries(stations);
    if (entries.length === 0) {
      replaceChildren(this.container, el("p", { class: "empty", text: "No station data loaded." }));
      return;
    }

    const sorted = entries.sort(([, a], [, b]) => {
      if (a.distance_km !== null && b.distance_km !== null) return a.distance_km - b.distance_km;
      if (a.distance_km !== null) return -1;
      if (b.distance_km !== null) return 1;
      return a.name.localeCompare(b.name);
    });

    const filtered = sorted.filter(([, station]) => {
      if (this.maxRadiusMiles === 0) return true; // 0 = All
      if (station.distance_km === null && (station as any).distance_miles === undefined) return true;
      const miles = (station as any).distance_miles ?? (station.distance_km !== null ? station.distance_km * 0.621371 : null);
      return miles !== null ? miles <= this.maxRadiusMiles : true;
    });

    const anyDistance = sorted.some(([, station]) => station.distance_km !== null);

    const radiusSelect = el(
      "select",
      { class: "filter-select station-radius-select", attrs: { "aria-label": "Station Monitoring Radius" } },
      el("option", { attrs: { value: "50" }, text: "Within 50 miles" }),
      el("option", { attrs: { value: "100" }, text: "Within 100 miles" }),
      el("option", { attrs: { value: "250" }, text: "Within 250 miles" }),
      el("option", { attrs: { value: "0" }, text: "All Nationwide Stations" })
    ) as HTMLSelectElement;

    radiusSelect.value = String(this.maxRadiusMiles);
    radiusSelect.addEventListener("change", () => {
      this.maxRadiusMiles = Number(radiusSelect.value);
      this.page = 0;
      this.render();
    });

    const headerBar = el(
      "div",
      { class: "station-header-bar" },
      el("span", { class: "station-header-label", text: `Monitoring Radius:` }),
      radiusSelect,
      el("span", { class: "station-header-count", text: `${filtered.length} station(s) in range` })
    );

    const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    this.page = Math.min(this.page, pageCount - 1);
    const start = this.page * PAGE_SIZE;
    const pageItems = filtered.slice(start, start + PAGE_SIZE);

    replaceChildren(
      this.container,
      anyDistance
        ? headerBar
        : el("p", {
            class: "stations-summary",
            text: "Set TOCSIN_LATITUDE/TOCSIN_LONGITUDE (see .env.example) to sort these by distance.",
          }),
      pageItems.length > 0
        ? el(
            "ul",
            { class: "station-grid" },
            ...pageItems.map(([callsign, station]) => stationCard(callsign, station))
          )
        : el("p", { class: "empty", text: "No stations found within selected distance radius." }),
      pageCount > 1 ? this.pager(pageCount) : null
    );
  }

  private pager(pageCount: number): HTMLElement {
    const prev = el("button", { class: "pager-button", text: "‹ Prev", attrs: { type: "button" } });
    const next = el("button", { class: "pager-button", text: "Next ›", attrs: { type: "button" } });
    prev.disabled = this.page === 0;
    next.disabled = this.page >= pageCount - 1;
    prev.addEventListener("click", () => {
      this.page -= 1;
      this.render();
    });
    next.addEventListener("click", () => {
      this.page += 1;
      this.render();
    });
    return el(
      "div",
      { class: "pager" },
      prev,
      el("span", { class: "pager-status", text: `Page ${this.page + 1} of ${pageCount}` }),
      next
    );
  }
}

function stationCard(callsign: string, station: NwrStation): HTMLElement {
  const abnormal = station.status.toUpperCase() !== "NORMAL";
  const distMiles = (station as any).distance_miles ?? (station.distance_km !== null ? (station.distance_km * 0.621371).toFixed(1) : null);
  const distText = distMiles !== null ? `${distMiles} mi (${station.distance_km?.toFixed(1)} km)` : null;

  return el(
    "li",
    { class: `station-card${abnormal ? " station-abnormal" : ""}` },
    el(
      "div",
      { class: "station-card-head" },
      el("span", { class: "station-dot", attrs: { "aria-hidden": "true" } }),
      el("span", { class: "station-name", text: station.name }),
      distText ? el("span", { class: "station-dist-pill", text: distText }) : null
    ),
    el(
      "div",
      { class: "station-card-sub" },
      el("span", { class: "station-callsign", text: callsign }),
      el("span", { class: "station-bullet", text: "·" }),
      el("span", { class: "station-freq", text: `${station.frequency_mhz.toFixed(3)} MHz` }),
      el("span", { class: "station-bullet", text: "·" }),
      el("span", { class: "station-wfo", text: station.wfo }),
      abnormal ? el("span", { class: "station-status-tag", text: station.status }) : null
    )
  );
}
