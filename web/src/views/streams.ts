import { badge, el, reconcile, replaceChildren } from "../dom";
import type { Store } from "../store";
import type { StreamRow } from "../types";

/**
 * Live audio. The Icecast mounts `live_audio` pushes have always worked --
 * `http://host:8000/home-WX1.ogg` plays in VLC today -- but nothing in the
 * UI ever mentioned them, so they were discoverable only by reading
 * `live_audio/feeder.py`.
 *
 * Playback goes directly to Icecast rather than through `api`: an
 * `<audio>` element streams cross-origin without CORS, and proxying
 * continuous audio would pin an API connection open per listener for no
 * benefit. `icecast:8000` only resolves inside the compose network, so
 * the browser-facing base URL comes from `/system` when configured and
 * otherwise falls back to this page's own hostname on the Icecast port.
 *
 * Why this is a view object rather than a render function: the panel
 * repaints on every `/streams` poll (15s, and the listener count changes
 * on that tick precisely *because* someone started listening), and a
 * repaint that rebuilt the list detached the playing `<audio>` element --
 * which the HTML spec requires the browser to pause. Listening therefore
 * ended a few seconds after it began, every time. Each mount's `<li>` and
 * its player are created once and kept; a repaint patches the header
 * around them and never touches `src`, since assigning `src` reloads the
 * media element even when the value is unchanged.
 *
 * One caveat is inherent to the format, not this code: `live_audio`
 * encodes Ogg/Vorbis (see `build_ffmpeg_command`), which Safari and iOS
 * do not decode. Those browsers get the direct link rather than a player
 * that would silently fail.
 */

const OGG_UNSUPPORTED_NOTE = "Ogg/Vorbis — your browser may not play this inline; the link opens it directly.";

function canPlayOgg(): boolean {
  return document.createElement("audio").canPlayType('audio/ogg; codecs="vorbis"') !== "";
}

/** The mount URLs `api` returns are built from the *server's* view of
 * Icecast, which is `icecast:8000` inside compose -- unreachable from the
 * browser. Rewrite onto the page's own host unless an explicit public URL
 * is configured. */
function playbackUrl(row: StreamRow, publicBase: string | null, icecastPort: number | null): string {
  if (publicBase) return `${publicBase}${row.mount}`;
  const port = icecastPort ?? 8000;
  return `${window.location.protocol}//${window.location.hostname}:${port}${row.mount}`;
}

/** The long-lived nodes of one mount's row. */
interface Row {
  node: HTMLElement;
  header: HTMLElement;
  audio: HTMLAudioElement | null;
  link: HTMLAnchorElement;
  url: string;
}

export class StreamsView {
  private readonly container: HTMLElement;
  private readonly store: Store;
  private readonly rows = new Map<string, Row>();
  private readonly list = el("ul", { class: "stream-list" });
  private readonly oggPlayable = canPlayOgg();

  constructor(container: HTMLElement, store: Store) {
    this.container = container;
    this.store = store;
  }

  render(): void {
    const { streams, system, errors } = this.store.state;
    const error = errors.get("streams");
    const nodes: HTMLElement[] = [];

    if (error) {
      nodes.push(el("p", { class: "panel-error", text: `Streams unavailable — ${error}` }));
    }

    if (!streams) {
      this.rows.clear();
      if (!error) nodes.push(el("p", { class: "empty", text: "Loading streams…" }));
      replaceChildren(this.container, ...nodes);
      return;
    }

    // A failed poll says the API didn't answer, not that the mounts went
    // away: the banner goes above the last known list rather than
    // replacing it, so one bad request doesn't cut off a listener.
    if (!streams.icecast_reachable) {
      nodes.push(
        el("p", {
          class: "panel-error",
          text: "Icecast is not reachable from the API — streams below are what live-audio believes it is sending.",
        }),
      );
    }

    if (streams.streams.length === 0) {
      this.rows.clear();
      nodes.push(
        el("p", {
          class: "empty",
          text: streams.icecast_reachable
            ? "No streams running. live-audio creates a mount the first time audio arrives on a channel."
            : "No streams known.",
        }),
      );
      replaceChildren(this.container, ...nodes);
      return;
    }

    if (!this.oggPlayable) nodes.push(el("p", { class: "note", text: OGG_UNSUPPORTED_NOTE }));

    const publicBase = system?.icecast_public_url ?? null;
    const icecastPort = system?.icecast_port ?? null;
    const visible = streams.streams.map((row) => this.rowFor(row, playbackUrl(row, publicBase, icecastPort)));
    for (const mount of [...this.rows.keys()]) {
      if (!streams.streams.some((row) => row.mount === mount)) this.rows.delete(mount);
    }
    reconcile(this.list, visible);

    nodes.push(this.list);
    reconcile(this.container, nodes);
  }

  private rowFor(row: StreamRow, url: string): HTMLElement {
    let entry = this.rows.get(row.mount);
    if (!entry) {
      entry = createRow(row, url, this.oggPlayable);
      this.rows.set(row.mount, entry);
    }

    entry.node.className = row.on_air ? "stream on-air" : "stream off-air";
    replaceChildren(entry.header, ...headerParts(row));
    if (url !== entry.url) {
      entry.url = url;
      entry.link.href = url;
      // Only on an actual change: assigning `src` reloads the element,
      // which would stop playback on every repaint again.
      if (entry.audio) entry.audio.src = url;
    }
    return entry.node;
  }
}

function createRow(row: StreamRow, url: string, oggPlayable: boolean): Row {
  const header = el("div", { class: "stream-header" });
  const audio = oggPlayable
    ? (el("audio", { class: "stream-audio", attrs: { controls: "", preload: "none", src: url } }) as HTMLAudioElement)
    : null;
  const link = el("a", { class: "stream-link", text: row.mount, attrs: { href: url, rel: "noreferrer" } });

  if (audio) {
    audio.volume = 0.5;
    audio.addEventListener("play", () => {
      header.querySelector(".stream-equalizer")?.classList.add("eq-active");
    });
    audio.addEventListener("pause", () => {
      header.querySelector(".stream-equalizer")?.classList.remove("eq-active");
    });
    audio.addEventListener("ended", () => {
      header.querySelector(".stream-equalizer")?.classList.remove("eq-active");
    });
  }

  const node = el("li", {}, header, audio, link);
  return { node, header, audio, link, url };
}

function headerParts(row: StreamRow): (HTMLElement | null)[] {
  const label = row.site && row.channel ? `${row.site} · ${row.channel}` : row.mount;
  return [
    el("span", { class: "stream-name", text: label }),
    equalizerVisualizer(),
    row.on_air ? badge("on air", "alive") : badge("off air", "dead"),
    row.feeder_alive === false ? badge("feeder dead", "dead") : null,
    typeof row.listeners === "number"
      ? el("span", { class: "stream-listeners", text: `${row.listeners} listening` })
      : null,
  ];
}

function equalizerVisualizer(): HTMLElement {
  return el(
    "div",
    { class: "stream-equalizer" },
    el("span", { class: "eq-bar eq-bar-1" }),
    el("span", { class: "eq-bar eq-bar-2" }),
    el("span", { class: "eq-bar eq-bar-3" }),
    el("span", { class: "eq-bar eq-bar-4" })
  );
}

