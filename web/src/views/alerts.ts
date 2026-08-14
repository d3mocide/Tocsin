import { captureUrl, fetchDispatches, fetchTranscripts } from "../api";
import { badge, el, field, reconcile, replaceChildren } from "../dom";
import {
  absoluteTime,
  apiSource,
  areaLabel,
  captureName,
  countyNames,
  durationSeconds,
  expiresAt,
  isActive,
  relativeTime,
  rfApiLatencySeconds,
  rfSource,
  siteOf,
  tierOf,
  transcriptSource,
} from "../format";
import type { Store } from "../store";
import type { Alert, Dispatch, Reference, Transcript } from "../types";

/** Per-alert detail fetched on expand and cached. Fetched rather than
 * filtered out of the activity feed the sidebar already holds: that feed
 * is capped at the most recent rows, so an alert from two days ago would
 * silently render as "no transcript" instead of showing the one that
 * exists. */
interface AlertDetail {
  transcripts: Transcript[];
  dispatches: Dispatch[];
}

/** Desktop: a scrolling log with "load more" at the bottom. */
const PAGE_SIZE = 40;
/** Mobile: true prev/next pagination -- five cards is roughly one
 * screenful on a phone, keeping the pager and filter bar reachable
 * without scrolling past an unbounded feed. */
const MOBILE_PAGE_SIZE = 5;

const mobileQuery = window.matchMedia("(max-width: 900px)");

export class AlertFeedView {
  private readonly container: HTMLElement;
  private readonly store: Store;
  private readonly details = new Map<string, AlertDetail>();
  private readonly pending = new Set<string>();
  /** Rendered card keyed by alert id, with the signature it was built
   * from, so a repaint reuses every card whose content didn't change.
   * Rebuilding all of them (the old `replaceChildren` of freshly built
   * nodes) is what dropped the feed's scroll position and made a busy
   * system flash. */
  private readonly cards = new Map<string, { node: HTMLElement; signature: string }>();
  private limit = PAGE_SIZE;
  private mobilePage = 0;
  private lastFilterSignature = "";

  constructor(container: HTMLElement, store: Store) {
    this.container = container;
    this.store = store;
  }

  render(): void {
    const { alerts, reference, expandedAlertId, errors } = this.store.state;
    const error = errors.get("alerts");
    if (error) {
      this.cards.clear();
      replaceChildren(this.container, el("p", { class: "panel-error", text: `Alert feed unavailable — ${error}` }));
      return;
    }

    const filterSignature = JSON.stringify(this.store.state.filters);
    if (filterSignature !== this.lastFilterSignature) {
      this.lastFilterSignature = filterSignature;
      this.limit = PAGE_SIZE;
      this.mobilePage = 0;
    }

    const now = new Date();
    const matching = [...alerts.values()]
      .filter((alert) => this.matches(alert, reference, now))
      .sort(byUrgencyThenRecency(reference, now));

    if (matching.length === 0) {
      this.cards.clear();
      const empty = alerts.size === 0 ? "No alerts yet." : "No alerts match the current filters.";
      replaceChildren(this.container, el("p", { class: "empty", text: empty }));
      return;
    }

    if (mobileQuery.matches) {
      this.renderMobile(matching, reference, now, expandedAlertId);
    } else {
      this.renderDesktop(matching, reference, now, expandedAlertId);
    }
  }

  private renderDesktop(
    matching: Alert[],
    reference: Reference | null,
    now: Date,
    expandedAlertId: string | null,
  ): void {
    const visible = matching.slice(0, this.limit);
    const nodes: HTMLElement[] = visible.map((alert) =>
      this.cardFor(alert, reference, now, alert.id === expandedAlertId),
    );

    for (const id of [...this.cards.keys()]) {
      if (!visible.some((alert) => alert.id === id)) this.cards.delete(id);
    }

    const hidden = matching.length - visible.length;
    if (hidden > 0) nodes.push(this.moreButton(hidden));
    reconcile(this.container, nodes);
  }

  private renderMobile(
    matching: Alert[],
    reference: Reference | null,
    now: Date,
    expandedAlertId: string | null,
  ): void {
    const pageCount = Math.max(1, Math.ceil(matching.length / MOBILE_PAGE_SIZE));
    this.mobilePage = Math.min(this.mobilePage, pageCount - 1);
    const start = this.mobilePage * MOBILE_PAGE_SIZE;
    const visible = matching.slice(start, start + MOBILE_PAGE_SIZE);

    const nodes: HTMLElement[] = visible.map((alert) =>
      this.cardFor(alert, reference, now, alert.id === expandedAlertId),
    );

    for (const id of [...this.cards.keys()]) {
      if (!visible.some((alert) => alert.id === id)) this.cards.delete(id);
    }

    if (pageCount > 1) nodes.push(this.mobilePager(pageCount, matching.length));
    reconcile(this.container, nodes);
  }

  private moreButton(hidden: number): HTMLElement {
    const button = el("button", {
      class: "feed-more",
      text: `Show ${Math.min(hidden, PAGE_SIZE)} more (${hidden} older ${hidden === 1 ? "alert" : "alerts"} hidden)`,
      attrs: { type: "button" },
    });
    button.addEventListener("click", () => {
      this.limit += PAGE_SIZE;
      this.render();
    });
    return button;
  }

  private mobilePager(pageCount: number, total: number): HTMLElement {
    const prev = el("button", { class: "pager-button", text: "‹ Prev", attrs: { type: "button" } });
    const next = el("button", { class: "pager-button", text: "Next ›", attrs: { type: "button" } });
    (prev as HTMLButtonElement).disabled = this.mobilePage === 0;
    (next as HTMLButtonElement).disabled = this.mobilePage >= pageCount - 1;
    prev.addEventListener("click", () => {
      this.mobilePage -= 1;
      this.render();
      this.container.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    next.addEventListener("click", () => {
      this.mobilePage += 1;
      this.render();
      this.container.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return el(
      "div",
      { class: "pager" },
      prev,
      el("span", { class: "pager-status", text: `${this.mobilePage + 1} / ${pageCount}  ·  ${total} alerts` }),
      next,
    );
  }

  /** Builds a card only when its rendered content would differ from the
   * one already on screen. The signature covers everything `card()` reads,
   * including the two clock-derived strings -- which is why a card holding
   * an open `<audio>` element survives the 15s repaint tick. */
  private cardFor(alert: Alert, reference: Reference | null, now: Date, expanded: boolean): HTMLElement {
    const signature = [
      alert.last_updated,
      alert.state,
      alert.confidence,
      alert.event_name,
      alert.fips_codes.join(","),
      alert.sources.length,
      tierOf(alert, reference) ?? "",
      String(isActive(alert, now)),
      relativeTime(alert.last_updated, now),
      expiryLabel(alert, now),
      String(expanded),
      expanded ? String(this.details.has(alert.id)) : "",
    ].join("|");

    const cached = this.cards.get(alert.id);
    if (cached && cached.signature === signature) return cached.node;
    const node = this.card(alert, reference, now, expanded);
    this.cards.set(alert.id, { node, signature });
    return node;
  }

  private matches(alert: Alert, reference: Reference | null, now: Date): boolean {
    const { state, tier, site, query, activeOnly } = this.store.state.filters;
    if (state && alert.state !== state) return false;
    if (tier && tierOf(alert, reference) !== tier) return false;
    if (site && siteOf(alert) !== site) return false;
    if (activeOnly && !isActive(alert, now)) return false;
    if (query) {
      const haystack = [
        alert.event_name,
        alert.fips_codes.join(" "),
        countyNames(alert.fips_codes, reference),
        rfSource(alert)?.event_code ?? "",
        apiSource(alert)?.headline ?? "",
        apiSource(alert)?.area_desc ?? "",
        transcriptSource(alert)?.matched_phrase ?? "",
        transcriptSource(alert)?.transcript_text ?? "",
      ]
        .join(" ")
        .toLowerCase();
      if (!haystack.includes(query.toLowerCase())) return false;
    }
    return true;
  }

  private card(alert: Alert, reference: Reference | null, now: Date, expanded: boolean): HTMLElement {
    const tier = tierOf(alert, reference);
    const active = isActive(alert, now);
    // Tier A is the set that reaches the mesh immediately (design doc §4)
    // -- an active one is the loudest thing this page can show, which is
    // the treatment `health.ts` already gives a dead RF channel.
    const alarm = active && tier === "A";

    const classes = ["alert-card", `state-${alert.state.toLowerCase()}`];
    if (tier) classes.push(`tier-${tier.toLowerCase()}`);
    if (!active) classes.push("expired");
    if (alarm) classes.push("alarm");
    if (expanded) classes.push("expanded");

    const card = el("article", { class: classes.join(" "), attrs: { "data-alert-id": alert.id } });

    const header = el("button", {
      class: "alert-header",
      attrs: { type: "button", "aria-expanded": String(expanded) },
    });
    header.addEventListener("click", () => this.toggle(alert));

    const area = areaLabel(alert, reference);

    header.append(
      el(
        "div",
        { class: "alert-badges" },
        tier ? badge(`Tier ${tier}`, `tier-${tier.toLowerCase()}`) : null,
        badge(alert.state.replace("_", " "), alert.state.toLowerCase()),
        !active ? badge("expired", "expired") : null,
      ),
      el("h3", { class: "alert-title", text: alert.event_name }),
      el("p", { class: "alert-counties", text: area.text, attrs: { title: area.title } }),
      el(
        "p",
        { class: "alert-meta" },
        el("span", { text: relativeTime(alert.last_updated, now), title: absoluteTime(alert.last_updated) }),
        el("span", { class: "sep", text: "·" }),
        el("span", { text: expiryLabel(alert, now) }),
        el("span", { class: "sep", text: "·" }),
        el("span", { text: `confidence ${alert.confidence.toFixed(2)}` }),
      ),
      el("span", { class: "alert-chevron", text: expanded ? "−" : "+", attrs: { "aria-hidden": "true" } }),
    );

    card.append(header);
    if (expanded) card.append(this.detail(alert, reference, now));
    return card;
  }

  private toggle(alert: Alert): void {
    const alreadyOpen = this.store.state.expandedAlertId === alert.id;
    this.store.update("alerts", (state) => {
      state.expandedAlertId = alreadyOpen ? null : alert.id;
    });
    if (!alreadyOpen) void this.loadDetail(alert);
  }

  private async loadDetail(alert: Alert): Promise<void> {
    if (this.details.has(alert.id) || this.pending.has(alert.id)) return;
    const rawHeader = rfSource(alert)?.raw_header;
    if (!rawHeader) {
      // No RF source means no SAME header, and raw_header is the only key
      // transcripts and dispatches are recorded under. A pure API_ONLY
      // alert genuinely has nothing there; a TRANSCRIPT_ONLY alert's
      // "transcript" is already embedded directly on its keyword-event
      // source (see transcriptSourcePanel below), not fetched from this
      // endpoint. Either way, resolve immediately rather than leaving the
      // card on "Loading detail…" forever.
      this.details.set(alert.id, { transcripts: [], dispatches: [] });
      return;
    }
    this.pending.add(alert.id);
    try {
      const [transcripts, dispatches] = await Promise.all([
        fetchTranscripts(20, rawHeader),
        fetchDispatches(20, rawHeader),
      ]);
      this.details.set(alert.id, { transcripts, dispatches });
    } catch (err) {
      console.error("failed to load alert detail", err);
      this.details.set(alert.id, { transcripts: [], dispatches: [] });
    } finally {
      this.pending.delete(alert.id);
      this.store.notify("alerts");
    }
  }

  private detail(alert: Alert, reference: Reference | null, now: Date): HTMLElement {
    const rf = rfSource(alert);
    const cap = apiSource(alert);
    const transcript = transcriptSource(alert);
    const latency = rfApiLatencySeconds(alert);
    const detail = this.details.get(alert.id);
    const mode = this.store.state.system?.mode;

    return el(
      "div",
      { class: "alert-detail" },
      latency !== null
        ? el(
            "p",
            { class: "latency" },
            // The number the dual-path architecture exists to produce:
            // negative means the radio beat the API, which is the point.
            latency <= 0
              ? `Radio heard it ${durationSeconds(latency)} before NWS published it.`
              : `NWS published it ${durationSeconds(latency)} before the radio heard it.`,
          )
        : null,
      el(
        "div",
        { class: "provenance" },
        rfPanel(rf, reference),
        capPanel(cap, mode),
      ),
      transcript ? transcriptSourcePanel(transcript) : null,
      detail ? transcriptPanel(detail.transcripts) : el("p", { class: "empty", text: "Loading detail…" }),
      detail ? dispatchPanel(detail.dispatches, now) : null,
    );
  }
}

function expiryLabel(alert: Alert, now: Date): string {
  const expiry = expiresAt(alert);
  if (!expiry) return "no expiry given";
  return expiry.getTime() > now.getTime()
    ? `expires ${relativeTime(expiry.toISOString(), now)}`
    : `expired ${relativeTime(expiry.toISOString(), now)}`;
}

/** Sort: active before expired, then Tier A first, then most recent. An
 * expired tornado warning must never sit above a live one. */
function byUrgencyThenRecency(reference: Reference | null, now: Date) {
  const tierRank = (alert: Alert) => ({ A: 0, B: 1, C: 2 })[tierOf(alert, reference) ?? ""] ?? 3;
  return (a: Alert, b: Alert): number => {
    const activeDelta = Number(isActive(b, now)) - Number(isActive(a, now));
    if (activeDelta !== 0) return activeDelta;
    const tierDelta = tierRank(a) - tierRank(b);
    if (tierDelta !== 0) return tierDelta;
    return new Date(b.last_updated).getTime() - new Date(a.last_updated).getTime();
  };
}

function rfPanel(rf: ReturnType<typeof rfSource>, reference: Reference | null): HTMLElement {
  const body = rf
    ? el(
        "dl",
        { class: "fields" },
        field("Event code", rf.event_code, { mono: true }),
        field("Tier", rf.tier),
        field("Received", `${absoluteTime(rf.received_at)}`),
        field("Source", `${rf.site} / ${rf.channel}`),
        field("Originator", rf.originator),
        field("Callsign", rf.callsign),
        field("Purge", `${rf.purge_minutes} min`),
        field("Areas", countyNames(rf.fips_codes, reference)),
        field("Raw header", rf.raw_header, { mono: true }),
      )
    : el("p", { class: "empty", text: "No SAME header — this alert was never heard on the radio." });

  return el(
    "section",
    { class: "provenance-panel provenance-rf" },
    el("h4", { text: "What the radio heard" }),
    body,
  );
}

function capPanel(cap: ReturnType<typeof apiSource>, mode: string | null | undefined): HTMLElement {
  // An empty CAP column means two completely different things depending
  // on mode, and the page can only say which because /system tells it.
  const emptyReason =
    mode === "hybrid"
      ? "No CAP alert correlated — NWS has not published a matching alert."
      : "No CAP alert — offgrid mode does not poll the NWS API at all.";

  const body = cap
    ? el(
        "dl",
        { class: "fields" },
        field("Headline", cap.headline),
        field("Severity", cap.severity),
        field("Certainty", cap.certainty),
        field("Urgency", cap.urgency),
        field("Category", cap.category),
        field("Area", cap.area_desc),
        field("Sent", absoluteTime(cap.sent)),
        field("Effective", absoluteTime(cap.effective)),
        field("Onset", absoluteTime(cap.onset)),
        field("Expires", absoluteTime(cap.expires ?? cap.ends)),
        field("VTEC", cap.vtec, { mono: true }),
        field("Status", `${cap.status} / ${cap.message_type}`),
      )
    : el("p", { class: "empty", text: emptyReason });

  return el(
    "section",
    { class: "provenance-panel provenance-api" },
    el("h4", { text: "What NWS said" }),
    body,
  );
}

/** A TRANSCRIPT_ONLY alert's provenance -- a keyword hit in continuously-
 * transcribed NWR narration (`stt_worker.keyword_match`), never a decoded
 * SAME header. The matched phrase and its source sentence are already
 * embedded on the alert itself (`transcriptSource`), unlike `rfPanel`/
 * `capPanel`'s detail, which is a separate fetch keyed on `raw_header`. */
function transcriptSourcePanel(transcript: ReturnType<typeof transcriptSource>): HTMLElement | null {
  if (!transcript) return null;
  return el(
    "section",
    { class: "provenance-panel provenance-transcript" },
    el("h4", { text: "What the live transcript caught" }),
    el(
      "dl",
      { class: "fields" },
      field("Matched phrase", transcript.matched_phrase, { mono: true }),
      field("Tier", transcript.tier),
      field("Heard", absoluteTime(transcript.received_at)),
      field("Source", `${transcript.site} / ${transcript.channel}`),
    ),
    el("p", { class: "transcript-text", text: transcript.transcript_text }),
    el("p", {
      class: "empty",
      text: "No SAME header — caught by keyword match in continuous transcription, not a decoded alert.",
    }),
  );
}

function transcriptPanel(transcripts: Transcript[]): HTMLElement {
  if (transcripts.length === 0) {
    return el(
      "section",
      { class: "detail-section" },
      el("h4", { text: "Voice message" }),
      el("p", { class: "empty", text: "No transcript recorded for this header." }),
    );
  }

  return el(
    "section",
    { class: "detail-section" },
    el("h4", { text: "Voice message" }),
    ...transcripts.map((transcript) => {
      const name = captureName(transcript.wav_path);
      return el(
        "div",
        { class: transcript.passed_guard ? "transcript" : "transcript guard-failed" },
        el(
          "p",
          { class: "transcript-meta" },
          badge(transcript.passed_guard ? "guard passed" : "guard failed", transcript.passed_guard ? "alive" : "dead"),
          el("span", { text: `${transcript.site} / ${transcript.channel}` }),
        ),
        transcript.passed_guard
          ? el("p", { class: "transcript-text", text: transcript.text })
          : // stt_worker drops the text of a transcript that looks
            // hallucinated, so guard_reason is the only record of why --
            // and this is exactly the case where the audio matters most.
            el("p", { class: "transcript-text empty", text: `Text withheld: ${transcript.guard_reason ?? "hallucination guard"}` }),
        name ? el("audio", { class: "capture-audio", attrs: { controls: "", preload: "none", src: captureUrl(name) } }) : null,
      );
    }),
  );
}

function dispatchPanel(dispatches: Dispatch[], now: Date): HTMLElement {
  if (dispatches.length === 0) {
    return el(
      "section",
      { class: "detail-section" },
      el("h4", { text: "Dispatch" }),
      el("p", { class: "empty", text: "No dispatch decision recorded for this header." }),
    );
  }

  return el(
    "section",
    { class: "detail-section" },
    el("h4", { text: "Dispatch" }),
    el(
      "ul",
      { class: "dispatch-list" },
      ...dispatches.map((dispatch) =>
        el(
          "li",
          { class: dispatch.sent ? "dispatch sent" : "dispatch not-sent" },
          badge(dispatch.sent ? "sent" : "not sent", dispatch.sent ? "alive" : "dead"),
          el("span", { class: "dispatch-reason", text: dispatch.reason }),
          el("span", { class: "dispatch-stage", text: `stage ${dispatch.stage}` }),
          el("span", {
            class: "dispatch-time",
            text: relativeTime(dispatch.dispatched_at, now),
            title: absoluteTime(dispatch.dispatched_at),
          }),
        ),
      ),
    ),
  );
}
