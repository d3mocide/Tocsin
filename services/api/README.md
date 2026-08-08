# api

FastAPI REST + SSE feed over the canonical alert store (design doc §10
milestone 8). The first service in this repo to actually write to
TimescaleDB -- every prior phase's alert/health work deliberately stood
in with a `Logging*Sink`/Redis-only path because standing up a real
Postgres schema wasn't that phase's dependency; this is where it happens.

Consumes four Redis Streams via consumer groups -- `fusion`'s
`tocsin:alerts`, `sdr_rx`'s `tocsin:health`, `stt_worker`'s
`tocsin:transcripts`, and `dispatcher`'s `tocsin:dispatches` -- writing
each to Postgres and fanning all four out live to any connected `/events`
SSE client as named events. Spectrum data is read straight from
`sdr_rx`'s per-site `tocsin:spectrum:<site>` Redis key on request -- no
Postgres involved, since a waterfall display only ever wants the latest
snapshot, not history (see `spectrum.py`'s docstring). Per-service
liveness comes from the `tocsin:status:<service>` keys each service
SETEXes from its own main loop (`status.py`).

Also serves `web/`'s built SPA -- formerly its own nginx container, now
a build stage in this service's `Dockerfile` (a `node:22` stage builds
`web/`'s `dist/`, copied into this image's `static/`). `create_app`
mounts it at `/` via `StaticFiles`, registered after every API route
below so an exact-path route always wins over the catch-all (e.g. `GET
/alerts` never falls through to the SPA). Set `API_STATIC_DIR` to
override where it looks, or leave it unset/empty to disable the mount
entirely (`config.py`'s default, `/app/static`, simply won't exist in
plain `uv run api` dev use, which is fine -- `create_app` only mounts a
directory that's actually there).

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /alerts?limit=&state=` | Recent alerts from Postgres, newest first, optionally filtered by state. |
| `GET /events` | SSE feed carrying named `alert`, `health`, `transcript`, and `dispatch` events. Clients use `addEventListener(name, ...)`; `onmessage` only fires for unnamed events. |
| `GET /health` | Latest RF health sample per `(site, channel)`. |
| `GET /health/history?since_seconds=&buckets=` | Down-sampled RF health per `(site, channel)` for sparklines. Bucketed in Postgres via `time_bucket`; `dead` is `BOOL_OR`'d, never averaged. |
| `GET /transcripts?limit=&raw_header=` | Stored transcripts. `raw_header` is the only identifier shared between an alert's RF source and a transcript, so it's how the UI attaches one to the other. |
| `GET /dispatches?limit=&raw_header=` | What `dispatcher` decided, including every negative outcome (`skipped_rate_limited`, `serial_no_ack`, ...). |
| `GET /spectrum` | Sites with a current spectrum snapshot. |
| `GET /spectrum/{site}` | Latest 48-bin spectrum snapshot for one site (404 if none yet). |
| `GET /stats` | Alert state counts, the `RF_ONLY`/`API_ONLY` divergence rate (design doc §5's stated system health metric), and a sent-vs-skipped dispatch summary. |
| `GET /services` | Per-service liveness from the heartbeat keys, compared against the set expected *in this mode* -- a crashed service is reported `down`, not omitted. |
| `GET /system` | `TOCSIN_MODE` and the browser-facing Icecast URL. |
| `GET /streams` | Icecast mountpoints, merged from Icecast's `status-json.xsl` and `live_audio`'s heartbeat. |
| `GET /reference` | `data/`'s SAME event codes (name + tier) and FIPS -> county table, served once for the UI to resolve client-side. |
| `GET /captures/{name}` | One finished capture WAV. Basename only, re-checked to be inside `API_CAPTURES_DIR` after resolution -- `wav_path` reaches this from a Redis payload, so trusting it as a filesystem path would make this an arbitrary-file read. |

## Status

Implemented and unit tested: the Postgres schema (`schema.sql`, applied
idempotently at startup) and query functions (`db.py`), the Redis
consumer-group wiring for all four inbound streams (`redis_bus.py`, async
version of the same crash-replay pattern `fusion`/`dispatcher` use, tested
against a hand-written async fake of Redis's stream semantics), the
ingestion-to-Postgres-plus-SSE-fan-out wiring (`ingest.py`), the SSE
broadcast hub (`sse.py`), the spectrum snapshot reader (`spectrum.py`),
the heartbeat reader (`status.py`), the Icecast status merge
(`streams.py`), the reference-data loader (`reference.py`), and every REST
route (`app.py`, tested via FastAPI's `TestClient` against fake
Postgres/Redis -- no real database or Redis instance in this authoring
sandbox).

**Known gaps, not yet handled:**
- No auth (design doc §9 names "reverse proxy + Argon2id local backend
  auth" -- out of scope for this phase, which is about the data path, not
  the deploy-behind-Caddy story).
- `/alerts` has no pagination beyond `limit` (no cursor/offset) -- fine at
  current expected alert volumes, not designed for years of history.
- Not verified against a real Postgres, Redis, or live upstream producers
  -- verified against fakes and fixtures only.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `API_POSTGRES_DSN` | *(required)* | e.g. `postgresql://tocsin:<password>@timescaledb:5432/tocsin`. Refuses to start without it. |
| `API_REDIS_URL` | `redis://redis:6379/0` | Redis connection URL. |
| `API_CONSUMER_NAME` | `api` | Redis consumer-group consumer name (fixed, not hostname-derived -- same reasoning as `fusion`/`dispatcher`). |
| `API_HOST` / `API_PORT` | `0.0.0.0` / `8000` | uvicorn bind address. |
| `API_STATIC_DIR` | `/app/static` | Directory containing `web/`'s built `dist/`. Mounted at `/` if it exists; set to empty to disable the SPA mount entirely. |
| `TOCSIN_MODE` | `offgrid` | Reported by `GET /system` and used to decide which services `GET /services` expects (`nws_poller` is hybrid-only). |
| `TOCSIN_DATA_DIR` | *(unset)* | Directory holding `same_event_codes.yaml` and `fips.csv` for `GET /reference`. Unset or missing degrades to an empty reference rather than refusing to start -- unlike every other service, where a missing tier table would mean mis-tiering a real warning. |
| `API_CAPTURES_DIR` | *(unset)* | `segment_capture`'s output directory. Unset makes `GET /captures/{name}` a 404. |
| `ICECAST_HOST` / `ICECAST_PORT` | `icecast` / `8000` | Where *this process* reaches Icecast to read its status page. |
| `ICECAST_PUBLIC_URL` | *(unset)* | Where the *browser* should reach Icecast. Unset means the page falls back to its own hostname on `ICECAST_PORT`, which is right for a LAN deployment; set it behind a reverse proxy. |

## Development

```sh
uv sync
uv run pytest
```
