import { el, replaceChildren } from "../dom";
import type { Store } from "../store";
import type { NwrStation } from "../types";

/**
 * NWR transmitters from `GET /reference`'s `stations` table (design doc §12
 * open item on verifying local transmitter frequencies -- see
 * `data/nwr_stations_or.yaml`). Sorted by `distance_km` when the operator
 * has set `TOCSIN_LATITUDE`/`TOCSIN_LONGITUDE`; alphabetical otherwise, so
 * the list is still useful as a plain directory with no location configured.
 *
 * This is a UI hint for antenna/gain bring-up and reading the spectrum
 * waterfall, not identification: several stations here share a channel, so
 * "nearest on this frequency" narrows down what a bin is probably carrying
 * without replacing the empirical listen-and-confirm the open item calls
 * for.
 *
 * A class rather than a render function, like `StreamsView`/`WaterfallView`:
 * unlike those, there's no data reason for state here (nothing streams or
 * accumulates), but the 3x2 page needs to remember which page it's on
 * across repaints -- a plain function starting over at page 0 every time
 * `reference` reloads would fight anyone mid-page-through.
 */
const PAGE_SIZE = 6; // 3 columns x 2 rows -- see style.css's .station-grid

export class StationsView {
  private readonly container: HTMLElement;
  private readonly store: Store;
  private page = 0;

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
    const anyDistance = sorted.some(([, station]) => station.distance_km !== null);

    const pageCount = Math.ceil(sorted.length / PAGE_SIZE);
    // Clamped rather than reset to 0: the only way this shrinks below the
    // current page is the reference table itself shrinking, which doesn't
    // happen on a running deployment -- but a clamp is one line cheaper
    // than reasoning about whether it can, and costs nothing when it can't.
    this.page = Math.min(this.page, pageCount - 1);
    const start = this.page * PAGE_SIZE;
    const pageItems = sorted.slice(start, start + PAGE_SIZE);

    replaceChildren(
      this.container,
      anyDistance
        ? null
        : el("p", {
            class: "stations-summary",
            text: "Set TOCSIN_LATITUDE/TOCSIN_LONGITUDE (see .env.example) to sort these by distance.",
          }),
      el(
        "ul",
        { class: "station-grid" },
        ...pageItems.map(([callsign, station]) => stationCard(callsign, station)),
      ),
      pageCount > 1 ? this.pager(pageCount) : null,
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
      next,
    );
  }
}

function stationCard(callsign: string, station: NwrStation): HTMLElement {
  const abnormal = station.status.toUpperCase() !== "NORMAL";
  return el(
    "li",
    { class: `station-card${abnormal ? " station-abnormal" : ""}` },
    el(
      "div",
      { class: "station-card-head" },
      el("span", { class: "station-dot", attrs: { "aria-hidden": "true" } }),
      el("span", { class: "station-name", text: station.name }),
    ),
    el("div", { class: "station-callsign", text: callsign }),
    el("div", {
      class: "station-distance",
      text: station.distance_km !== null ? `${station.distance_km.toFixed(1)} km` : "—",
      title: station.distance_km === null ? "operator location unset, or this station's coordinates are unconfirmed" : "",
    }),
    el("div", {
      class: "station-detail",
      text: abnormal
        ? `${station.frequency_mhz.toFixed(3)} MHz · ${station.wfo} · ${station.status}`
        : `${station.frequency_mhz.toFixed(3)} MHz · ${station.wfo}`,
    }),
  );
}
