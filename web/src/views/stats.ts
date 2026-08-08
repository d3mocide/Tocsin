import { el, replaceChildren } from "../dom";
import type { Store } from "../store";
import type { Stats } from "../types";

/** The headline metrics. The divergence rate keeps the primary tile --
 * design doc §5 calls it "the best single health metric for the whole
 * system" -- but it is now stated in words as well as a percentage,
 * because a bare "66.7%" gives no clue whether high is good or bad. */
export function renderStats(container: HTMLElement, store: Store): void {
  const { stats, errors } = store.state;
  const error = errors.get("stats");
  if (error) {
    replaceChildren(container, el("p", { class: "panel-error", text: `Stats unavailable — ${error}` }));
    return;
  }
  if (!stats) {
    replaceChildren(container, el("p", { class: "empty", text: "Loading…" }));
    return;
  }

  replaceChildren(
    container,
    el(
      "div",
      { class: "stat-tile stat-tile-primary" },
      el("div", { class: "stat-value", text: `${(stats.divergence_rate * 100).toFixed(1)}%` }),
      el("div", { class: "stat-label", text: "RF/API divergence" }),
      el("p", { class: "stat-note", text: divergenceNote(stats) }),
    ),
    ...(["CONFIRMED", "RF_ONLY", "API_ONLY"] as const).map((state) =>
      el(
        "div",
        { class: `stat-tile stat-${state.toLowerCase()}` },
        el("div", { class: "stat-value", text: String(stats.counts[state] ?? 0) }),
        el("div", { class: "stat-label", text: state.replace("_", " ") }),
      ),
    ),
  );
}

function divergenceNote(stats: Stats): string {
  if (stats.total === 0) return "No alerts recorded yet.";
  const divergent = (stats.counts.RF_ONLY ?? 0) + (stats.counts.API_ONLY ?? 0);
  return `${divergent} of ${stats.total} alerts seen by only one path`;
}
