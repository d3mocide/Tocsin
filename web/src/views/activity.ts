import { badge, byIdOptional, el, replaceChildren } from "../dom";
import { absoluteTime, apiSource, relativeTime, siteOf, tierOf } from "../format";
import type { Store } from "../store";
import type { Alert, Dispatch, Transcript } from "../types";

/**
 * Activity log card surfacing only active alert events and sent dispatches
 * with Severity / Tier A or B. Skipped activity and ambient live chatter are
 * discarded to keep this panel high-signal.
 */

type ActivityEntry =
  | { kind: "dispatch"; at: number; dispatch: Dispatch }
  | { kind: "alert"; at: number; alert: Alert; tier: string }
  | { kind: "transcript"; at: number; transcript: Transcript };

export function renderActivity(container: HTMLElement, store: Store): void {
  const { dispatches, alerts, transcripts, reference, errors } = store.state;
  const error = errors.get("activity");
  if (error) {
    replaceChildren(container, el("p", { class: "panel-error", text: `Activity unavailable — ${error}` }));
    return;
  }

  const entries: ActivityEntry[] = [];

  // Sent dispatches for Tier A or B only (discard skipped activity)
  for (const dispatch of dispatches) {
    if (dispatch.sent && (dispatch.tier === "A" || dispatch.tier === "B")) {
      entries.push({
        kind: "dispatch",
        at: new Date(dispatch.dispatched_at).getTime(),
        dispatch,
      });
    }
  }

  // Alerts with Tier A or B
  for (const alert of alerts.values()) {
    const tier = tierOf(alert, reference);
    if (tier === "A" || tier === "B") {
      entries.push({
        kind: "alert",
        at: new Date(alert.first_seen).getTime(),
        alert,
        tier,
      });
    }
  }

  // Voice transcripts from SAME alerts with Tier A or B (ambient LIVE chunks are in the transcripts feed)
  for (const transcript of transcripts) {
    if (transcript.event_code !== "LIVE" && (transcript.tier === "A" || transcript.tier === "B")) {
      entries.push({
        kind: "transcript",
        at: transcript.timestamp_ns / 1e6,
        transcript,
      });
    }
  }

  // Deduplicate and sort newest first
  entries.sort((a, b) => b.at - a.at);

  const headerSummary = byIdOptional("activity-header-summary");
  if (headerSummary) {
    replaceChildren(
      headerSummary,
      el("span", { class: "badge badge-status-idle", text: `${entries.length} LOGGED` }),
    );
  }

  if (entries.length === 0) {
    replaceChildren(container, el("p", { class: "empty", text: "No Tier A or B alert activity recorded yet." }));
    return;
  }

  replaceChildren(
    container,
    el("ul", { class: "activity-list" }, ...entries.slice(0, 50).map(activityRow)),
  );
}

function activityRow(entry: ActivityEntry): HTMLElement {
  const iso = new Date(entry.at).toISOString();
  const time = el("span", { class: "activity-time", text: relativeTime(iso), title: absoluteTime(iso) });

  if (entry.kind === "dispatch") {
    const { dispatch } = entry;
    return el(
      "li",
      { class: "activity activity-dispatch sent" },
      el(
        "div",
        { class: "activity-head" },
        badge(`Tier ${dispatch.tier}`, `tier-${dispatch.tier.toLowerCase()}`),
        badge(dispatch.stage, "alive"),
        el("span", { class: "activity-code", text: dispatch.event_code }),
        dispatch.site && dispatch.channel ? el("span", { class: "activity-where", text: `${dispatch.site}/${dispatch.channel}` }) : null,
        time,
      ),
      el("p", { class: "activity-text mono", text: dispatch.reason }),
    );
  }

  if (entry.kind === "alert") {
    const { alert, tier } = entry;
    const site = siteOf(alert);
    const cap = apiSource(alert);
    const headline = cap?.headline || alert.event_name;

    return el(
      "li",
      { class: `activity activity-alert tier-${tier.toLowerCase()}` },
      el(
        "div",
        { class: "activity-head" },
        badge(`Tier ${tier}`, `tier-${tier.toLowerCase()}`),
        badge(alert.state, alert.state.toLowerCase()),
        el("span", { class: "activity-code", text: alert.event_name }),
        site ? el("span", { class: "activity-where", text: site }) : null,
        time,
      ),
      el("p", { class: "activity-text", text: headline }),
    );
  }

  const { transcript } = entry;
  return el(
    "li",
    { class: `activity activity-transcript tier-${transcript.tier.toLowerCase()}` },
    el(
      "div",
      { class: "activity-head" },
      badge(`Tier ${transcript.tier}`, `tier-${transcript.tier.toLowerCase()}`),
      badge("transcript", "api_only"),
      el("span", { class: "activity-code", text: transcript.event_code }),
      el("span", { class: "activity-where", text: `${transcript.site}/${transcript.channel}` }),
      time,
    ),
    el("p", {
      class: transcript.passed_guard ? "activity-text" : "activity-text empty",
      text: transcript.passed_guard
        ? transcript.text
        : `Guard failed: ${transcript.guard_reason ?? "hallucination guard"}`,
    }),
  );
}
