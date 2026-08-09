# web

Vite + TypeScript UI (design doc §9, §10 milestone 8). Talks to
`services/api`.

Builds into `services/api`'s own container image rather than running as
its own container -- `services/api/Dockerfile` has a `node:22` build
stage for this directory, and `api`'s `app.py` serves the built `dist/`
as static files. There's no `web/Dockerfile` or nginx config here
anymore; see `services/api/README.md` for how the merged container
works and why.

Vanilla TypeScript, no framework. The design doc names "Vite + TypeScript
UI" without specifying one, and at this scope -- eight panels, all
server-driven, no routing and no client-side form state -- a framework
would be more build surface than it removes. What the rebuild *did* add is
`store.ts`, a single observable state object with one flat listener list,
because the previous design had each view owning its own polling timer and
rebuilding itself via `innerHTML`, which is what made per-panel error
states and preserved scroll/focus impossible.

No CDN, no webfont, no external asset of any kind. That's the offgrid rule
(`CLAUDE.md`) applied to the frontend: a stylesheet reaching for
`fonts.googleapis.com` renders a degraded page on exactly the deployment
this system exists for.

## Layout

Two columns on desktop. The left carries **Live audio**, **Nearby NWR stations**, the
**alert feed**, and the **activity log**; the right carries the spectrum, RF channels,
system health, services, and dispatch. Nearby NWR stations sits in the wider left column
rather than with the other radio-hardware panels on the right because its 3-column card
grid needs the width; RF channels stays on the right in a narrower auto-fit grid. Audio and
activity started on the right and moved because five stacked panels there against a lone
feed on the left left the page visibly lopsided.

The audio players lay out as a responsive grid rather than a stack, so the wide left column
is used horizontally and three mounts don't push the alert feed down the page.

Below 900px everything collapses to one column and the alert feed is reordered to the top:
audio above the feed balances two columns, but on one narrow column it would push the thing
you opened the page for below the fold.

## What's on the page

- **Alert feed** (`views/alerts.ts`) -- expandable cards. Collapsed shows
  tier, state, county names, relative time, and expiry. Expanded shows
  *both* provenance sources side by side ("What the radio heard" / "What
  NWS said"), which is design doc §5's "never a merged blob" model made
  visible, plus the RF↔API latency, the voice transcript with its capture
  audio, and every dispatch decision for that SAME header.
  - Sorting is active-before-expired, then Tier A first, then recency. An
    expired tornado warning must never sit above a live one.
  - An active Tier A alert gets the loudest treatment on the page and a
    count in the tab title -- the same threshold `dispatcher` uses to
    decide what reaches the mesh (design doc §4).
- **System health** (`views/stats.ts`) -- the `RF_ONLY`/`API_ONLY`
  divergence rate (design doc §5's stated system health metric), now
  stated in words as well as a percentage, plus per-state counts.
- **Services** (`views/status.ts`) -- per-service liveness from
  `GET /services`. Compares against the set expected *in this mode*, so a
  crashed service reads "down" rather than quietly vanishing from the
  list. `nws-poller`'s row surfaces its last poll result, since a poller
  failing every call to api.weather.gov looks exactly like a quiet night
  from anywhere else on this page.
- **Dispatch** -- sent vs skipped over the last 24h with a reason
  breakdown. Answers "did anything actually reach the mesh," which no
  other number on the page can.
- **Spectrum** (`views/spectrum.ts`) -- a scrolling waterfall over the
  48-bin snapshot, newest row at the top, with the 7 NWR channel bins
  labelled and colored distinctly from the 41 spectrum-only bins (design
  doc §3). The dB scale is **fixed**, unlike the bar chart this replaced,
  which rescaled to each frame's own min/max -- that made the display
  breathe with the noise floor and made a carrier appearing look identical
  to the noise floor dropping.
- **RF channels** (`views/health.ts`) -- per-`(site, channel)` health, one
  card per channel (dot + name, sparkline, RMS/last-sample/status detail
  line) in an auto-fit grid rather than one full-width row per channel --
  a single column wasted most of the panel's width on seven short rows.
  `dead: true` (design doc §3's flat-carrier signal) still gets the
  loudest treatment, with a sparkline seeded from `GET /health/history` so
  a channel drifting toward dead is visible before it crosses the
  threshold.
- **Nearby NWR stations** (`views/stations.ts`) -- `GET /reference`'s
  station table (`data/nwr_stations_or.yaml`), sorted by `distance_km` when
  the operator has set `TOCSIN_LATITUDE`/`TOCSIN_LONGITUDE`
  (`services/api/README.md`), alphabetical otherwise. A UI hint for antenna/
  gain bring-up and reading the waterfall's channel labels, not station
  identification -- several stations share a channel, so this narrows down
  what a bin probably carries without replacing an actual listen-and-confirm.
  A fixed 3-column, 2-row page (6 stations) with Prev/Next paging through
  the rest, rather than a long scrolling list or a "show more" that grows
  the panel -- `StationsView` keeps the current page across repaints
  (`reference` reloading, e.g.) so paging through doesn't get reset out
  from under you.
- **Live audio** (`views/streams.ts`) -- an `<audio>` player per Icecast
  mount. These streams always worked; nothing in the UI ever mentioned
  them. Each mount's player is created once and kept for the panel's
  lifetime: the panel repaints on every 15s `/streams` poll, and a media
  element removed from the document is paused by the browser, so a panel
  that rebuilt its rows cut playback off within seconds of starting it.
- **Activity** (`views/activity.ts`) -- a merged transcript/dispatch log.
  The feed answers "what happened to this alert"; this answers "is
  anything happening at all," and is where a transcript with no matching
  alert becomes visible instead of having nowhere to appear.

## Transport

One SSE connection (`GET /events`) carries alerts, health samples,
transcripts, and dispatch outcomes as named events. Only three things
still poll, because they have no push feed to ride on: spectrum (a Redis
snapshot key `sdr_rx` overwrites in place), services (heartbeat keys), and
streams (Icecast's status page). Health used to poll on a 5s timer, which
meant a channel going dead could sit unrendered for those 5s.

A fourth timer repaints on a 15s tick with no data change at all, because
relative timestamps and the active/expired split are derived from the
clock -- without it an expired warning would keep claiming to expire "in 2
minutes" forever.

## Verification

Rendered in a real browser (headless Chromium) against a stub API serving
`services/api`'s exact response shapes, at desktop and mobile widths:
no console or page errors, no horizontal page scroll at either width, and
the filters, card expansion, transcript/dispatch fetch, audio elements,
and tab-title badge all confirmed working. `npm run build` (which runs
`tsc --noEmit` first) passes.

Not yet rendered against a *real* `api` backed by real Postgres/Redis with
live upstream producers -- see `docs/design/tracking.md` for what
"verified" means for each piece of this phase.

## Configuration

`VITE_API_BASE_URL` (build-time, via `.env.local` for `npm run dev`):
defaults to same-origin, unprefixed, since the production build is
served directly by the `api` service that also owns those routes (no
proxy or prefix-stripping involved). Local dev against a real `api`
running on its default port needs `VITE_API_BASE_URL=http://localhost:8000`
in `.env.local`, since Vite's dev server doesn't serve `api`'s routes
itself.

Icecast playback URLs are *not* built from `VITE_API_BASE_URL` -- they
come from `GET /system`'s `icecast_public_url` when the deployment sets
one, and otherwise from this page's own hostname on `GET /system`'s
`icecast_port` (`ICECAST_PORT`, `8000` by default). The URLs `api` returns
are built from its own view of Icecast (`icecast:<ICECAST_PORT>` inside
compose), which the browser can't resolve.

## Development

```sh
npm install
npm run dev      # Vite dev server, hot reload
npm run build    # tsc --noEmit, then the production build into dist/
```
