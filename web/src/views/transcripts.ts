import { badge, byIdOptional, el, replaceChildren } from "../dom";
import { absoluteTime, relativeTime } from "../format";
import type { Store } from "../store";
import type { Transcript } from "../types";

/** `stt_worker.service.LIVE_EVENT_CODE` -- a continuously-transcribed chunk
 * of ordinary narration rather than a SAME-triggered voice message. */
const LIVE_EVENT_CODE = "LIVE";

export function isLiveTranscript(transcript: Transcript): boolean {
  return transcript.event_code === LIVE_EVENT_CODE;
}

export function renderTranscripts(container: HTMLElement, store: Store): void {
  const { transcripts, errors } = store.state;
  const error = errors.get("activity");
  if (error) {
    replaceChildren(container, el("p", { class: "panel-error", text: `Transcripts unavailable — ${error}` }));
    return;
  }

  const headerSummary = byIdOptional("transcripts-header-summary");
  if (headerSummary) {
    const liveCount = transcripts.filter(isLiveTranscript).length;
    const summaryText = liveCount > 0 ? `${transcripts.length} LOGGED (${liveCount} LIVE)` : `${transcripts.length} LOGGED`;
    replaceChildren(
      headerSummary,
      el("span", { class: "badge badge-status-idle", text: summaryText }),
    );
  }

  if (transcripts.length === 0) {
    replaceChildren(container, el("p", { class: "empty", text: "No voice transcripts recorded yet." }));
    return;
  }

  // Sort newest first
  const sorted = [...transcripts].sort((a, b) => b.timestamp_ns - a.timestamp_ns);

  replaceChildren(
    container,
    el("ul", { class: "activity-list transcripts-feed" }, ...sorted.slice(0, 100).map(transcriptRow)),
  );
}

function transcriptRow(transcript: Transcript): HTMLElement {
  const live = isLiveTranscript(transcript);
  const iso = new Date(transcript.timestamp_ns / 1e6).toISOString();
  const time = el("span", { class: "activity-time", text: relativeTime(iso), title: absoluteTime(iso) });

  const badgeEl = live
    ? badge("live", "transcript_only")
    : transcript.tier && (transcript.tier === "A" || transcript.tier === "B" || transcript.tier === "C")
      ? badge(`Tier ${transcript.tier}`, `tier-${transcript.tier.toLowerCase()}`)
      : badge("transcript", "api_only");

  return el(
    "li",
    { class: `activity activity-transcript${live ? " activity-live" : ""}` },
    el(
      "div",
      { class: "activity-head" },
      badgeEl,
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

export function renderDashboardLiveTranscripts(container: HTMLElement, store: Store): void {
  const { transcripts } = store.state;
  const liveTranscripts = transcripts.filter(isLiveTranscript);

  if (liveTranscripts.length === 0) {
    container.style.display = "none";
    replaceChildren(container);
    return;
  }

  container.style.display = "block";
  const recent = liveTranscripts.slice(0, 3);
  const latestSite = recent[0].site;
  const latestChannel = recent[0].channel;

  const head = el(
    "div",
    { class: "dashboard-transcripts-head" },
    el(
      "div",
      { class: "dashboard-transcripts-title" },
      el("span", { class: "live-pulse-dot", attrs: { "aria-hidden": "true" } }),
      el("span", { class: "dashboard-transcripts-heading", text: "Live Voice Transcription" }),
      el("span", { class: "badge badge-transcript_only", text: `${latestSite}/${latestChannel}` }),
    ),
    el("span", { class: "dashboard-transcripts-count", text: `${liveTranscripts.length} chunks` }),
  );

  const rows = recent.map((t, idx) => {
    const iso = new Date(t.timestamp_ns / 1e6).toISOString();
    const isLatest = idx === 0;
    return el(
      "div",
      { class: `dashboard-transcript-row${isLatest ? " latest" : ""}` },
      el(
        "div",
        { class: "activity-head" },
        badge("live", "transcript_only"),
        el("span", { class: "activity-code", text: t.channel }),
        el("span", { class: "activity-where", text: `${t.site}/${t.channel}` }),
        el("span", { class: "activity-time", text: relativeTime(iso), title: absoluteTime(iso) }),
      ),
      el("p", {
        class: t.passed_guard ? "activity-text" : "activity-text empty",
        text: t.passed_guard
          ? t.text
          : `Guard failed: ${t.guard_reason ?? "hallucination guard"}`,
      }),
    );
  });

  replaceChildren(
    container,
    head,
    el("div", { class: "dashboard-transcripts-body" }, ...rows),
  );
}
