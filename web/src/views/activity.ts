import { badge, byIdOptional, el, replaceChildren } from "../dom";
import { absoluteTime, relativeTime } from "../format";
import type { Store } from "../store";
import type { Dispatch, Transcript } from "../types";

/** A merged, newest-first log of transcripts and dispatch decisions.
 *
 * Both are also attached to their alert in the feed, but that view only
 * answers "what happened to this alert." This one answers "is anything
 * happening at all," which is the question during a quiet stretch when
 * you cannot tell a working system from a stopped one -- and it is where
 * a transcript with no matching alert (STT ran, fusion never produced an
 * alert) becomes visible instead of having nowhere to appear. */

type Entry =
  | { kind: "transcript"; at: number; transcript: Transcript }
  | { kind: "dispatch"; at: number; dispatch: Dispatch };

/** `stt_worker.service.LIVE_EVENT_CODE` -- a continuously-transcribed chunk
 * of ordinary narration rather than a SAME-triggered voice message. */
const LIVE_EVENT_CODE = "LIVE";

export function isLiveTranscript(transcript: Transcript): boolean {
  return transcript.event_code === LIVE_EVENT_CODE;
}

export function renderActivity(container: HTMLElement, store: Store): void {
  const { transcripts, dispatches, errors, showLiveTranscripts } = store.state;
  const error = errors.get("activity");
  if (error) {
    replaceChildren(container, el("p", { class: "panel-error", text: `Activity unavailable — ${error}` }));
    return;
  }

  // Continuous transcription produces a row every few seconds, which buries
  // alert activity in a feed capped at MAX_ACTIVITY_ROWS. Alert-only is the
  // default view for that reason; live rows are one click away, never a
  // permanent flood nobody asked for.
  const liveCount = transcripts.filter(isLiveTranscript).length;
  const shownTranscripts = showLiveTranscripts ? transcripts : transcripts.filter((t) => !isLiveTranscript(t));

  const entries: Entry[] = [
    // timestamp_ns is nanoseconds since the epoch; Date wants ms.
    ...shownTranscripts.map((transcript) => ({
      kind: "transcript" as const,
      at: transcript.timestamp_ns / 1e6,
      transcript,
    })),
    ...dispatches.map((dispatch) => ({
      kind: "dispatch" as const,
      at: new Date(dispatch.dispatched_at).getTime(),
      dispatch,
    })),
  ].sort((a, b) => b.at - a.at);

  const headerSummary = byIdOptional("activity-header-summary");
  if (headerSummary) {
    const children: (HTMLElement | null)[] = [
      el("span", { class: "badge badge-status-idle", text: `${entries.length} LOGGED` }),
    ];
    if (liveCount > 0) {
      const toggle = el("button", {
        class: `activity-live-toggle${showLiveTranscripts ? " on" : ""}`,
        text: showLiveTranscripts ? `Hide ${liveCount} live` : `Show ${liveCount} live`,
        attrs: { type: "button", "aria-pressed": String(showLiveTranscripts) },
      });
      toggle.addEventListener("click", () =>
        store.update("activity", (state) => {
          state.showLiveTranscripts = !state.showLiveTranscripts;
        }),
      );
      children.push(toggle);
    }
    replaceChildren(headerSummary, ...children);
  }

  if (entries.length === 0) {
    replaceChildren(container, el("p", { class: "empty", text: "Nothing recorded yet." }));
    return;
  }

  replaceChildren(
    container,
    el("ul", { class: "activity-list" }, ...entries.slice(0, 60).map(entryRow)),
  );
}


function entryRow(entry: Entry): HTMLElement {
  const iso = new Date(entry.at).toISOString();
  const time = el("span", { class: "activity-time", text: relativeTime(iso), title: absoluteTime(iso) });

  if (entry.kind === "transcript") {
    const { transcript } = entry;
    const live = isLiveTranscript(transcript);
    return el(
      "li",
      { class: `activity activity-transcript${live ? " activity-live" : ""}` },
      el(
        "div",
        { class: "activity-head" },
        live ? badge("live", "transcript_only") : badge("transcript", "api_only"),
        el("span", { class: "activity-code", text: live ? transcript.channel : transcript.event_code }),
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

  const { dispatch } = entry;
  return el(
    "li",
    { class: `activity activity-dispatch ${dispatch.sent ? "sent" : "not-sent"}` },
    el(
      "div",
      { class: "activity-head" },
      badge(dispatch.sent ? "dispatched" : "skipped", dispatch.sent ? "alive" : "rf_only"),
      el("span", { class: "activity-code", text: dispatch.event_code }),
      el("span", { class: "activity-where", text: `stage ${dispatch.stage}` }),
      time,
    ),
    el("p", { class: "activity-text mono", text: dispatch.reason }),
  );
}
