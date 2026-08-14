import { el, replaceChildren } from "../dom";
import type { Store } from "../store";
import type { Stats } from "../types";

/** The headline metrics card. Displays system health, path divergence rate,
 * visual distribution breakdown bar, and a balanced 4-metric grid. */
export function renderStats(container: HTMLElement, store: Store): void {
  const { stats, errors, system } = store.state;
  const error = errors.get("stats");
  if (error) {
    replaceChildren(container, el("p", { class: "panel-error", text: `Stats unavailable — ${error}` }));
    return;
  }
  if (!stats) {
    replaceChildren(container, el("p", { class: "empty", text: "Loading…" }));
    return;
  }

  const isOffgrid = system?.mode === "offgrid";
  const confirmed = stats.counts.CONFIRMED ?? 0;
  const rfOnly = stats.counts.RF_ONLY ?? 0;
  const apiOnly = stats.counts.API_ONLY ?? 0;
  // Not part of the RF/API divergence metric below (design doc §5 defines
  // that as an RF-vs-CAP comparison specifically) -- shown as its own
  // tile only once the deployment has actually used keyword detection,
  // so a stack that's never enabled live transcription doesn't carry a
  // permanently-zero tile.
  const transcriptOnly = stats.counts.TRANSCRIPT_ONLY ?? 0;
  const total = stats.total;

  const confirmedPct = total > 0 ? Math.round((confirmed / total) * 100) : 0;
  const rfOnlyPct = total > 0 ? Math.round((rfOnly / total) * 100) : 0;
  const apiOnlyPct = total > 0 ? Math.round((apiOnly / total) * 100) : 0;

  // System status badge classification
  let statusBadgeText = "SYNCED";
  let statusBadgeClass = "badge-status-synced";
  if (isOffgrid) {
    statusBadgeText = "OFFGRID MODE";
    statusBadgeClass = "badge-status-offgrid";
  } else if (total === 0) {
    statusBadgeText = "IDLE";
    statusBadgeClass = "badge-status-idle";
  } else if (confirmed > 0 && stats.divergence_rate < 0.3) {
    statusBadgeText = "OPTIMAL";
    statusBadgeClass = "badge-status-synced";
  } else if (apiOnly > 0 && rfOnly === 0 && confirmed === 0) {
    statusBadgeText = "API ONLY";
    statusBadgeClass = "badge-status-apionly";
  } else if (rfOnly > 0 && apiOnly === 0 && confirmed === 0) {
    statusBadgeText = "RF ONLY";
    statusBadgeClass = "badge-status-rfonly";
  } else {
    statusBadgeText = "DIVERGENT";
    statusBadgeClass = "badge-status-divergent";
  }

  // Segmented distribution progress bar
  const confirmedWidth = total > 0 ? (confirmed / total) * 100 : 0;
  const rfWidth = total > 0 ? (rfOnly / total) * 100 : 0;
  const apiWidth = total > 0 ? (apiOnly / total) * 100 : 0;

  replaceChildren(
    container,
    el(
      "div",
      { class: "stats-container" },
      // Main Primary Card
      el(
        "div",
        { class: "stat-tile stat-tile-primary" },
        el(
          "div",
          { class: "stat-header-row" },
          el("span", { class: "stat-primary-title", text: "Path Divergence" }),
          el("span", { class: `badge ${statusBadgeClass}`, text: statusBadgeText })
        ),
        el(
          "div",
          { class: "stat-primary-main" },
          el("div", { class: "stat-value-large", text: isOffgrid ? "N/A" : `${(stats.divergence_rate * 100).toFixed(1)}%` }),
          el("p", { class: "stat-note", text: divergenceNote(stats, isOffgrid) })
        ),
        // Segmented distribution bar
        el(
          "div",
          { class: "divergence-bar-container", title: `Distribution: ${confirmed} Confirmed (${confirmedPct}%), ${rfOnly} RF Only (${rfOnlyPct}%), ${apiOnly} API Only (${apiOnlyPct}%)` },
          el("div", { class: "divergence-bar-segment segment-confirmed", style: `width: ${confirmedWidth}%` }),
          el("div", { class: "divergence-bar-segment segment-rf", style: `width: ${rfWidth}%` }),
          el("div", { class: "divergence-bar-segment segment-api", style: `width: ${apiWidth}%` })
        )
      ),
      // Balanced 4-Column Metric Grid
      el(
        "div",
        { class: "stats-subgrid" },
        el(
          "div",
          { class: "stat-tile stat-confirmed" },
          el("div", { class: "stat-value", text: String(confirmed) }),
          el("div", { class: "stat-label", text: "Confirmed" }),
          el("div", { class: "stat-subtext", text: total > 0 ? `${confirmedPct}%` : "—" })
        ),
        el(
          "div",
          { class: "stat-tile stat-rf_only" },
          el("div", { class: "stat-value", text: String(rfOnly) }),
          el("div", { class: "stat-label", text: "RF Only" }),
          el("div", { class: "stat-subtext", text: total > 0 ? `${rfOnlyPct}%` : "—" })
        ),
        el(
          "div",
          { class: "stat-tile stat-api_only" },
          el("div", { class: "stat-value", text: String(apiOnly) }),
          el("div", { class: "stat-label", text: "API Only" }),
          el("div", { class: "stat-subtext", text: total > 0 ? `${apiOnlyPct}%` : "—" })
        ),
        transcriptOnly > 0
          ? el(
              "div",
              { class: "stat-tile stat-transcript_only" },
              el("div", { class: "stat-value", text: String(transcriptOnly) }),
              el("div", { class: "stat-label", text: "Transcript Only" }),
              el("div", { class: "stat-subtext", text: total > 0 ? `${Math.round((transcriptOnly / total) * 100)}%` : "—" })
            )
          : null,
        el(
          "div",
          { class: "stat-tile stat-total" },
          el("div", { class: "stat-value", text: String(total) }),
          el("div", { class: "stat-label", text: "Total" }),
          el("div", { class: "stat-subtext", text: "Alerts" })
        )
      )

    )
  );
}

function divergenceNote(stats: Stats, isOffgrid: boolean): string {
  if (isOffgrid) return "Offgrid mode — all RF alerts are primary.";
  if (stats.total === 0) return "No alerts recorded yet.";
  const divergent = (stats.counts.RF_ONLY ?? 0) + (stats.counts.API_ONLY ?? 0);
  return `${divergent} of ${stats.total} alert${stats.total === 1 ? "" : "s"} seen by only one path`;
}
