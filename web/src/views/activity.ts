import { badge, el, replaceChildren } from "../dom";
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

export function renderActivity(container: HTMLElement, store: Store): void {
  const { transcripts, dispatches, errors } = store.state;
  const error = errors.get("activity");
  if (error) {
    replaceChildren(container, el("p", { class: "panel-error", text: `Activity unavailable — ${error}` }));
    return;
  }

  const entries: Entry[] = [
    // timestamp_ns is nanoseconds since the epoch; Date wants ms.
    ...transcripts.map((transcript) => ({
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
    return el(
      "li",
      { class: "activity activity-transcript" },
      el(
        "div",
        { class: "activity-head" },
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
