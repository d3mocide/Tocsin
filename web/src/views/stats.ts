import { byIdOptional, el, replaceChildren } from "../dom";
import { tierOf } from "../format";
import type { Store } from "../store";

/**
 * Alert Ingestion Scorecard.
 *
 * Displays active life-safety emergency warnings (SAME broadcast sirens)
 * alongside regional CAP statements (Air Quality, Heat, Watches), with
 * real-time telemetry for RF SDR reception and NWS API polling.
 */
export function renderStats(container: HTMLElement, store: Store): void {
  const { stats, alerts, health, services, errors, system, reference } = store.state;
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
  const alertsList = Array.from(alerts.values());

  let warningCount = 0;
  let advisoryCount = 0;

  if (alertsList.length > 0) {
    for (const alert of alertsList) {
      const isSameWarning = alert.sources.some((s) => s.kind === "RF") || tierOf(alert, reference) === "A";
      if (isSameWarning) {
        warningCount++;
      } else {
        advisoryCount++;
      }
    }
  } else {
    warningCount = (stats.counts.CONFIRMED ?? 0) + (stats.counts.RF_ONLY ?? 0);
    advisoryCount = stats.counts.API_ONLY ?? 0;
  }

  const totalActive = warningCount + advisoryCount;

  // Header Summary Badge
  const headerSummary = byIdOptional("stats-header-summary");
  if (headerSummary) {
    replaceChildren(
      headerSummary,
      el("span", {
        class: `badge ${warningCount > 0 ? "badge-tier-a" : totalActive > 0 ? "badge-api_only" : "badge-status-idle"}`,
        text: totalActive === 0 ? "QUIET" : `${totalActive} ACTIVE`,
      }),
    );
  }

  // RF Health Pipeline Status
  const healthSamples = Array.from(health.values());
  const rfTotal = healthSamples.length || 7;
  const rfAlive = healthSamples.filter((s) => !s.dead).length;
  const rfHealthy = rfAlive > 0;

  // NWS Poller API Service Health
  const pollerService = services.find((s) => s.service === "nws_poller");
  const apiHealthy = isOffgrid ? false : pollerService ? pollerService.status === "up" : true;

  replaceChildren(
    container,
    el(
      "div",
      { class: "alert-ingestion-card" },
      // 2-Column Split Metric Scorecard
      el(
        "div",
        { class: "ingestion-split-grid" },
        // Column 1: SAME Broadcast Warnings
        el(
          "div",
          { class: `ingestion-col ingestion-col-warnings${warningCount > 0 ? " active-hazard" : ""}` },
          el(
            "div",
            { class: "ingestion-col-header" },
            el("span", { class: "ingestion-col-label", text: "SAME Broadcasts" }),
            el("span", { class: `badge ${warningCount > 0 ? "badge-tier-a" : "badge-status-synced"}`, text: warningCount > 0 ? "ACTIVE" : "QUIET" }),
          ),
          el(
            "div",
            { class: "ingestion-metric-row" },
            el("span", { class: `ingestion-val ${warningCount > 0 ? "val-hazard" : "val-quiet"}`, text: String(warningCount) }),
            el("span", { class: "ingestion-val-unit", text: warningCount === 1 ? "Warning" : "Warnings" }),
          ),
          el("div", { class: "ingestion-subtext", text: warningCount === 0 ? "No active broadcast sirens" : "Life-safety broadcast alerts" }),
        ),
        // Column 2: Regional Advisories (CAP)
        el(
          "div",
          { class: "ingestion-col ingestion-col-advisories" },
          el(
            "div",
            { class: "ingestion-col-header" },
            el("span", { class: "ingestion-col-label", text: "Regional Advisories" }),
            el("span", { class: `badge ${advisoryCount > 0 ? "badge-api_only" : "badge-status-idle"}`, text: advisoryCount > 0 ? "ACTIVE" : "CLEAR" }),
          ),
          el(
            "div",
            { class: "ingestion-metric-row" },
            el("span", { class: "ingestion-val val-advisory", text: String(advisoryCount) }),
            el("span", { class: "ingestion-val-unit", text: advisoryCount === 1 ? "Advisory" : "Advisories" }),
          ),
          el("div", { class: "ingestion-subtext", text: advisoryCount === 0 ? "No regional statements" : "NWS CAP statements & watches" }),
        ),
      ),
      // Seamless Pipeline Telemetry Footer
      el(
        "div",
        { class: "ingestion-telemetry-footer" },
        el(
          "div",
          { class: "telemetry-item" },
          el("span", { class: `pipeline-dot ${rfHealthy ? "dot-alive" : "dot-dead"}`, attrs: { "aria-hidden": "true" } }),
          el("span", { class: "telemetry-label", text: "RF SDR:" }),
          el("span", { class: "telemetry-value", text: `${rfAlive}/${rfTotal} Channels Live` }),
        ),
        el(
          "div",
          { class: "telemetry-item" },
          el("span", {
            class: `pipeline-dot ${isOffgrid ? "dot-offgrid" : apiHealthy ? "dot-alive" : "dot-dead"}`,
            attrs: { "aria-hidden": "true" },
          }),
          el("span", { class: "telemetry-label", text: "NWS API:" }),
          el("span", {
            class: "telemetry-value",
            text: isOffgrid ? "Offgrid Mode" : apiHealthy ? "Polling Active" : "Degraded",
          }),
        ),
      ),
    ),
  );
}
