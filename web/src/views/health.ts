import { badge, el, replaceChildren } from "../dom";
import { absoluteTime, relativeTime } from "../format";
import { healthKey, type Store } from "../store";
import type { HealthSample } from "../types";

const SPARKLINE_WIDTH = 72;
const SPARKLINE_HEIGHT = 20;

/** Per-(site, channel) RF health. `dead: true` -- design doc §3's flat-
 * carrier signal, the primary liveness indicator for the whole SDR path --
 * still gets the loudest treatment here, now with a sparkline of recent
 * RMS beside it so a channel that is *drifting* toward dead is visible
 * before it crosses the threshold. */
export function renderHealth(container: HTMLElement, store: Store): void {
  const { health, healthHistory, errors } = store.state;
  const error = errors.get("health");
  if (error) {
    replaceChildren(container, el("p", { class: "panel-error", text: `RF health unavailable — ${error}` }));
    return;
  }

  const samples = [...health.values()].sort(
    (a, b) => a.site.localeCompare(b.site) || a.channel.localeCompare(b.channel),
  );
  if (samples.length === 0) {
    replaceChildren(container, el("p", { class: "empty", text: "No health samples yet." }));
    return;
  }

  const deadCount = samples.filter((sample) => sample.dead).length;

  replaceChildren(
    container,
    deadCount > 0
      ? el("p", {
          class: "health-summary bad",
          text: `${deadCount} channel${deadCount === 1 ? "" : "s"} dead — flat carrier over 30s`,
        })
      : el("p", { class: "health-summary good", text: `${samples.length} channels alive` }),
    el(
      "table",
      { class: "health-table" },
      el(
        "thead",
        {},
        el(
          "tr",
          {},
          el("th", { text: "Site", attrs: { scope: "col" } }),
          el("th", { text: "Channel", attrs: { scope: "col" } }),
          el("th", { text: "RMS", attrs: { scope: "col" } }),
          el("th", { text: "Trend", attrs: { scope: "col" } }),
          el("th", { text: "Last sample", attrs: { scope: "col" } }),
          el("th", { text: "Status", attrs: { scope: "col" } }),
        ),
      ),
      el(
        "tbody",
        {},
        ...samples.map((sample) => row(sample, healthHistory.get(healthKey(sample.site, sample.channel)) ?? [])),
      ),
    ),
  );
}

function row(sample: HealthSample, series: number[]): HTMLElement {
  return el(
    "tr",
    { class: sample.dead ? "row-dead" : "row-alive" },
    el("td", { text: sample.site }),
    el("td", { text: sample.channel }),
    el("td", { class: "mono", text: sample.rms.toExponential(2) }),
    el("td", {}, sparkline(series, sample.dead)),
    el("td", { text: relativeTime(sample.sampled_at), title: absoluteTime(sample.sampled_at) }),
    el("td", {}, badge(sample.dead ? "DEAD" : "alive", sample.dead ? "dead" : "alive")),
  );
}

/** Hand-drawn SVG polyline rather than a chart library: this is sixty
 * points of one series with no axes, legend, or interaction, which is
 * several orders of magnitude less than any charting dependency is for. */
function sparkline(series: number[], dead: boolean): SVGElement {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "sparkline");
  svg.setAttribute("viewBox", `0 0 ${SPARKLINE_WIDTH} ${SPARKLINE_HEIGHT}`);
  svg.setAttribute("width", String(SPARKLINE_WIDTH));
  svg.setAttribute("height", String(SPARKLINE_HEIGHT));
  svg.setAttribute("aria-hidden", "true");

  if (series.length < 2) return svg;

  const min = Math.min(...series);
  const max = Math.max(...series);
  // A perfectly flat series is exactly the dead-carrier case, so it must
  // draw as a flat line rather than divide by a zero range.
  const range = max - min || 1;
  const step = SPARKLINE_WIDTH / (series.length - 1);

  const points = series
    .map((value, index) => {
      const x = index * step;
      const y = SPARKLINE_HEIGHT - ((value - min) / range) * (SPARKLINE_HEIGHT - 2) - 1;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  polyline.setAttribute("points", points);
  polyline.setAttribute("fill", "none");
  polyline.setAttribute("stroke", dead ? "var(--dead)" : "var(--accent)");
  polyline.setAttribute("stroke-width", "1.5");
  svg.append(polyline);
  return svg;
}
