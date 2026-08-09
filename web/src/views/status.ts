import { badge, byIdOptional, el, replaceChildren } from "../dom";
import { durationSeconds, relativeTime, serviceLabel } from "../format";
import type { Store } from "../store";
import type { ServiceRow } from "../types";

export function renderModeChip(container: HTMLElement, store: Store): void {
  const mode = store.state.system?.mode;
  if (!mode) {
    replaceChildren(container, el("span", { class: "chip chip-unknown", text: "mode unknown" }));
    return;
  }
  replaceChildren(
    container,
    el("span", {
      class: `chip chip-mode chip-${mode}`,
      text: mode,
      title:
        mode === "hybrid"
          ? "Hybrid: NWS API polling, remote STT, and MQTT fallback are active."
          : "Offgrid: no network components. RF path only, by design.",
    }),
  );
}

export function renderServices(container: HTMLElement, store: Store): void {
  const { services, errors } = store.state;
  const error = errors.get("services");
  if (error) {
    replaceChildren(container, el("p", { class: "panel-error", text: `Service status unavailable — ${error}` }));
    return;
  }
  if (services.length === 0) {
    replaceChildren(container, el("p", { class: "empty", text: "No service status yet." }));
    return;
  }

  const expectedServices = services.filter((r) => r.expected);
  const upServices = expectedServices.filter((r) => r.status === "up");
  const downServices = expectedServices.filter((r) => r.status === "down");

  const isAllGood = downServices.length === 0;

  const headerSummary = byIdOptional("services-header-summary");
  if (headerSummary) {
    replaceChildren(
      headerSummary,
      el("span", {
        class: `badge ${isAllGood ? "badge-status-synced" : "badge-status-divergent"}`,
        text: isAllGood ? `${upServices.length}/${expectedServices.length} ONLINE` : `${downServices.length} DOWN`,
      })
    );
  }

  replaceChildren(
    container,
    el(
      "div",
      { class: "services-container" },
      !isAllGood
        ? el(
            "div",
            { class: "services-summary-bar summary-bad" },
            el("span", { class: "badge badge-status-divergent", text: `${downServices.length} DOWN` }),
            el("span", { class: "services-summary-text", text: `${downServices.length} service(s) require attention` })
          )
        : null,
      el("ul", { class: "service-list" }, ...services.map(serviceRow))
    )
  );
}

/** Name and heartbeat age share the top row; the per-service detail gets a
 * row of its own below them. In one shared row the detail chip and the age
 * fought for the same few pixels -- a two-word chip wrapped the service
 * name onto a second line and a longer one ("polled 34 seconds ago") stacked
 * into a three-line block that made the card twice as tall as its
 * neighbours. Giving it its own line costs one line only on the services
 * that actually report a detail. */
function serviceRow(row: ServiceRow): HTMLElement {
  const detail = describeDetail(row);
  return el(
    "li",
    { class: `service service-${row.status}` },
    el(
      "div",
      { class: "service-head" },
      el(
        "div",
        { class: "service-left" },
        el("span", { class: "service-dot-pulse", attrs: { "aria-hidden": "true" } }),
        el("span", { class: "service-name", text: serviceLabel(row.service) })
      ),
      el("span", {
        class: "service-age",
        text: row.status === "down" ? "no heartbeat" : relativeTime(row.updated_at),
        title: row.updated_at ?? "never reported",
      })
    ),
    detail ? el("span", { class: "service-chip", text: detail.text, title: detail.title }) : null
  );
}

interface ServiceDetail {
  text: string;
  /** Hover text. The chip alone reads as jargon to anyone who didn't write
   * the service -- "chain: remote" and "polled 34 seconds ago" were both
   * reported as unreadable -- so every chip carries a sentence saying what
   * it's measuring and why it matters. */
  title: string;
}

function describeDetail(row: ServiceRow): ServiceDetail | null {
  const detail = row.detail ?? {};
  if (row.service === "nws_poller") {
    const lastError = detail.last_error;
    if (typeof lastError === "string" && lastError) {
      return {
        text: `NWS poll failed: ${lastError}`,
        title: "The last request to the National Weather Service API failed. RF (SAME) decoding is unaffected.",
      };
    }
    const lastSuccess = detail.last_success;
    if (typeof lastSuccess === "string") {
      return {
        text: `NWS checked ${relativeTime(lastSuccess)}`,
        title: "When this last successfully fetched alerts from the National Weather Service API (hybrid mode only).",
      };
    }
    return null;
  }
  if (row.service === "sdr_rx") {
    const running = detail.devices_running;
    const configured = detail.devices_configured;
    if (typeof running === "number" && typeof configured === "number") {
      return {
        text: running === configured ? `${running} radio${running === 1 ? "" : "s"}` : `${running}/${configured} radios`,
        title: `${running} of ${configured} configured RTL-SDR dongle(s) are receiving. Set with SDR_RX_DEVICES.`,
      };
    }
  }
  if (row.service === "stt_worker") {
    const chain = detail.chain;
    if (typeof chain === "string") {
      return {
        text: `transcribing: ${chain}`,
        title:
          chain === "remote"
            ? "Speech-to-text is going to a remote Whisper endpoint. Falls back to the local model if it's unreachable."
            : "Speech-to-text is running on this machine — no network needed.",
      };
    }
  }
  if (row.service === "dispatcher" && detail.stage2 === false) {
    return {
      text: "stage 2 off",
      title: "LLM enrichment is disabled. Stage 1 still dispatches alerts to the mesh on its own.",
    };
  }
  return null;
}

export function renderDispatchSummary(container: HTMLElement, store: Store): void {
  const dispatch = store.state.stats?.dispatch;
  if (!dispatch) {
    replaceChildren(container, el("p", { class: "empty", text: "No dispatch data yet." }));
    return;
  }

  const total = dispatch.sent + dispatch.skipped;
  const sentPct = total > 0 ? (dispatch.sent / total) * 100 : 0;
  const skippedPct = total > 0 ? (dispatch.skipped / total) * 100 : 0;

  const topReasons = Object.entries(dispatch.by_reason)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4);

  const headerSummary = byIdOptional("dispatch-header-summary");
  if (headerSummary) {
    replaceChildren(
      headerSummary,
      el("span", { class: "badge badge-status-synced", text: `${dispatch.sent} SENT` }),
      el("span", { class: "badge badge-status-rfonly", text: `${dispatch.skipped} SKIPPED` })
    );
  }

  replaceChildren(
    container,
    el(
      "div",
      { class: "dispatch-summary-container" },
      el(
        "div",
        { class: "dispatch-header-row" },
        el("span", { class: "dispatch-window-tag", text: `${durationSeconds(dispatch.since_seconds)} window` })
      ),
      el(
        "div",
        { class: "dispatch-bar-container", title: `Sent: ${dispatch.sent}, Skipped: ${dispatch.skipped}` },
        el("div", { class: "dispatch-bar-segment segment-sent", style: `width: ${sentPct}%` }),
        el("div", { class: "dispatch-bar-segment segment-skipped", style: `width: ${skippedPct}%` })
      ),
      total === 0
        ? el("p", { class: "empty", text: "Nothing dispatched in this window." })
        : el(
            "ul",
            { class: "reason-list" },
            ...topReasons.map(([reason, count]) =>
              el(
                "li",
                { class: "reason-item" },
                el("span", { class: "reason-name", text: formatReason(reason) }),
                el("span", { class: "reason-count-badge", text: String(count) })
              )
            )
          )
    )
  );
}




function formatReason(reason: string): string {
  const map: Record<string, string> = {
    duplicate: "Duplicate Alert",
    tier_c: "Tier C (Log Only)",
    disabled: "Dispatch Disabled",
    no_device: "No Hardware Device",
    low_confidence: "Low Confidence",
    rate_limited: "Rate Limited",
  };
  return map[reason] ?? reason.replace(/_/g, " ");
}

export function renderConnection(container: HTMLElement, store: Store): void {
  const connected = store.state.connected;
  replaceChildren(
    container,
    badge(connected ? "live" : "reconnecting…", connected ? "alive" : "reconnecting"),
  );
}
