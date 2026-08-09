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
 */
export function renderStations(container: HTMLElement, store: Store): void {
  const stations = store.state.reference?.stations ?? {};
  const entries = Object.entries(stations);
  if (entries.length === 0) {
    replaceChildren(container, el("p", { class: "empty", text: "No station data loaded." }));
    return;
  }

  const sorted = entries.sort(([, a], [, b]) => {
    if (a.distance_km !== null && b.distance_km !== null) return a.distance_km - b.distance_km;
    if (a.distance_km !== null) return -1;
    if (b.distance_km !== null) return 1;
    return a.name.localeCompare(b.name);
  });
  const anyDistance = sorted.some(([, station]) => station.distance_km !== null);

  replaceChildren(
    container,
    anyDistance
      ? null
      : el("p", {
          class: "stations-summary",
          text: "Set TOCSIN_LATITUDE/TOCSIN_LONGITUDE (see .env.example) to sort these by distance.",
        }),
    el("ul", { class: "station-list" }, ...sorted.map(([callsign, station]) => stationRow(callsign, station))),
  );
}

function stationRow(callsign: string, station: NwrStation): HTMLElement {
  const abnormal = station.status.toUpperCase() !== "NORMAL";
  return el(
    "li",
    { class: `station${abnormal ? " station-abnormal" : ""}` },
    el("span", { class: "station-dot", attrs: { "aria-hidden": "true" } }),
    el(
      "span",
      { class: "station-name" },
      `${station.name} `,
      el("span", { class: "station-callsign", text: callsign }),
    ),
    el("span", {
      class: "station-distance",
      text: station.distance_km !== null ? `${station.distance_km.toFixed(1)} km` : "—",
      title: station.distance_km === null ? "operator location unset, or this station's coordinates are unconfirmed" : "",
    }),
    el("span", {
      class: "station-detail",
      text: abnormal
        ? `${station.frequency_mhz.toFixed(3)} MHz · ${station.wfo} · ${station.status}`
        : `${station.frequency_mhz.toFixed(3)} MHz · ${station.wfo}`,
    }),
  );
}
