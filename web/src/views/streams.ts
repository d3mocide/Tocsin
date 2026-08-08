import { badge, el, replaceChildren } from "../dom";
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

export function renderStreams(container: HTMLElement, store: Store): void {
  const { streams, system, errors } = store.state;
  const error = errors.get("streams");
  if (error) {
    replaceChildren(container, el("p", { class: "panel-error", text: `Streams unavailable — ${error}` }));
    return;
  }
  if (!streams) {
    replaceChildren(container, el("p", { class: "empty", text: "Loading streams…" }));
    return;
  }

  const oggPlayable = canPlayOgg();
  const nodes: HTMLElement[] = [];

  if (!streams.icecast_reachable) {
    nodes.push(
      el("p", {
        class: "panel-error",
        text: "Icecast is not reachable from the API — streams below are what live-audio believes it is sending.",
      }),
    );
  }

  if (streams.streams.length === 0) {
    nodes.push(
      el("p", {
        class: "empty",
        text: streams.icecast_reachable
          ? "No streams running. live-audio creates a mount the first time audio arrives on a channel."
          : "No streams known.",
      }),
    );
    replaceChildren(container, ...nodes);
    return;
  }

  if (!oggPlayable) nodes.push(el("p", { class: "note", text: OGG_UNSUPPORTED_NOTE }));

  nodes.push(
    el(
      "ul",
      { class: "stream-list" },
      ...streams.streams.map((row) =>
        streamRow(row, playbackUrl(row, system?.icecast_public_url ?? null, system?.icecast_port ?? null), oggPlayable),
      ),
    ),
  );

  replaceChildren(container, ...nodes);
}

function streamRow(row: StreamRow, url: string, oggPlayable: boolean): HTMLElement {
  const label = row.site && row.channel ? `${row.site} · ${row.channel}` : row.mount;

  return el(
    "li",
    { class: row.on_air ? "stream on-air" : "stream off-air" },
    el(
      "div",
      { class: "stream-header" },
      el("span", { class: "stream-name", text: label }),
      row.on_air ? badge("on air", "alive") : badge("off air", "dead"),
      // `null` and `false` mean different things here: live_audio doesn't
      // know about this mount at all, versus it knows the feeder died.
      row.feeder_alive === false ? badge("feeder dead", "dead") : null,
      typeof row.listeners === "number"
        ? el("span", { class: "stream-listeners", text: `${row.listeners} listening` })
        : null,
    ),
    oggPlayable
      ? el("audio", { class: "stream-audio", attrs: { controls: "", preload: "none", src: url } })
      : null,
    el("a", {
      class: "stream-link",
      text: row.mount,
      attrs: { href: url, rel: "noreferrer" },
    }),
  );
}
