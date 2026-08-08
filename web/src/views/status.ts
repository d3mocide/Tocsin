import { badge, el, replaceChildren } from "../dom";
import { durationSeconds, relativeTime, serviceLabel } from "../format";
import type { Store } from "../store";
import type { ServiceRow } from "../types";

/** The strip across the top: mode, service liveness, and whether anything
 * is actually reaching the mesh. All three were previously unknowable
 * from this page -- mode wasn't exposed at all, no service published a
 * heartbeat, and dispatch outcomes existed only in container logs. */

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

  const down = services.filter((row) => row.expected && row.status === "down");

  replaceChildren(
    container,
    down.length > 0
      ? el("p", {
          class: "services-summary bad",
          text: `${down.length} of ${services.filter((r) => r.expected).length} services down`,
        })
      : el("p", { class: "services-summary good", text: "All expected services reporting" }),
    el("ul", { class: "service-list" }, ...services.map(serviceRow)),
  );
}

function serviceRow(row: ServiceRow): HTMLElement {
  const detail = describeDetail(row);
  return el(
    "li",
    { class: `service service-${row.status}` },
    el("span", { class: "service-dot", attrs: { "aria-hidden": "true" } }),
    el("span", { class: "service-name", text: serviceLabel(row.service) }),
    el("span", {
      class: "service-age",
      text: row.status === "down" ? "no heartbeat" : relativeTime(row.updated_at),
      title: row.updated_at ?? "never reported",
    }),
    detail ? el("span", { class: "service-detail", text: detail }) : null,
  );
}

/** Surfaces the few heartbeat details that answer a question the row
 * itself can't. nws-poller's is the important one: it reports "up" while
 * failing every call to api.weather.gov, which looks exactly like a quiet
 * night from anywhere else on this page. */
function describeDetail(row: ServiceRow): string | null {
  const detail = row.detail ?? {};
  if (row.service === "nws_poller") {
    const lastError = detail.last_error;
    if (typeof lastError === "string" && lastError) return `last poll failed: ${lastError}`;
    const lastSuccess = detail.last_success;
    if (typeof lastSuccess === "string") return `last poll ${relativeTime(lastSuccess)}`;
    return null;
  }
  if (row.service === "sdr_rx") {
    const running = detail.devices_running;
    const configured = detail.devices_configured;
    if (typeof running === "number" && typeof configured === "number") {
      return running === configured ? `${running} device(s)` : `${running}/${configured} devices running`;
    }
  }
  if (row.service === "dispatcher" && detail.stage2 === false) return "stage 2 disabled";
  return null;
}

export function renderDispatchSummary(container: HTMLElement, store: Store): void {
  const dispatch = store.state.stats?.dispatch;
  if (!dispatch) {
    replaceChildren(container, el("p", { class: "empty", text: "No dispatch data yet." }));
    return;
  }

  const total = dispatch.sent + dispatch.skipped;
  const topReasons = Object.entries(dispatch.by_reason)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4);

  replaceChildren(
    container,
    el(
      "div",
      { class: "dispatch-summary" },
      el(
        "p",
        { class: "dispatch-headline" },
        el("strong", { text: String(dispatch.sent) }),
        ` sent · ${dispatch.skipped} skipped`,
      ),
      el("p", {
        class: "dispatch-window",
        text: `last ${durationSeconds(dispatch.since_seconds)}`,
      }),
      total === 0
        ? el("p", { class: "empty", text: "Nothing dispatched in this window." })
        : el(
            "ul",
            { class: "reason-list" },
            ...topReasons.map(([reason, count]) =>
              el(
                "li",
                { class: "reason" },
                el("span", { class: "reason-name", text: reason }),
                el("span", { class: "reason-count", text: String(count) }),
              ),
            ),
          ),
    ),
  );
}

export function renderConnection(container: HTMLElement, store: Store): void {
  const connected = store.state.connected;
  replaceChildren(
    container,
    badge(connected ? "live" : "reconnecting…", connected ? "alive" : "reconnecting"),
  );
}
