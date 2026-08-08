# web

Vite + TypeScript UI (design doc §9, §10 milestone 8): alert feed (live
via SSE), RF channel health, spectrum display, and the `RF_ONLY`/
`API_ONLY` divergence rate as the headline system health metric (design
doc §5). Talks to `services/api`.

Vanilla TypeScript, no framework -- the design doc names "Vite + TypeScript
UI" without specifying one, and there's no way to visually verify UI
polish in this authoring sandbox regardless of framework choice, so this
stays proportionate: hand-authored DOM manipulation (`src/views/`), not a
scaffolded template or a component framework's build overhead.

## Status

Implemented, not yet run in a real browser against a real `api` backend
(no Docker daemon, and this session's sandbox has no way to visually
inspect a rendered page) -- `npm run build` (which runs `tsc --noEmit`
first) is the only verification performed here. See
`docs/design/tracking.md` for what "verified" actually means for each
piece of this phase.

- `src/api.ts`: REST fetch helpers + `subscribeToAlerts` (native
  `EventSource`, no SSE library needed).
- `src/views/alerts.ts`: live-updating alert feed. `upsert()` replaces an
  already-rendered alert in place rather than duplicating it when
  `fusion` republishes the same `id` on a state transition (`RF_ONLY` ->
  `CONFIRMED`).
- `src/views/health.ts`: per-`(site, channel)` RF health table --
  `dead: true` (design doc §3's flat-carrier signal) gets the loudest
  visual treatment on the page, not a quiet number.
- `src/views/spectrum.ts`: a plain canvas bar chart over the 48-bin
  snapshot `api`'s `/spectrum/{site}` returns, with the 7 NWR channel
  bins colored distinctly from the 41 spectrum-only bins (design doc §3).
- `src/views/stats.ts`: the divergence-rate tile plus per-state counts.
- `src/main.ts`: wires it together -- SSE for alerts (push), polling
  (`POLL_INTERVAL_MS`, 5s) for health/spectrum/stats, since those don't
  have a push feed of their own yet.

## Configuration

`VITE_API_BASE_URL` (build-time, via `.env.local` for `npm run dev`):
defaults to same-origin `/api`, which the production Dockerfile's nginx
config proxies to the `api` service (stripping the `/api` prefix -- see
`nginx.conf`). Local dev against a real `api` running on its default port
needs `VITE_API_BASE_URL=http://localhost:8000` in `.env.local`, since
Vite's dev server doesn't run the same nginx proxy.

## Development

```sh
npm install
npm run dev      # Vite dev server, hot reload
npm run build    # tsc --noEmit, then the production build into dist/
```
