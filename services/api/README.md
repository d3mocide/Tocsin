# api

FastAPI REST + SSE feed over the canonical alert store (design doc §10
milestone 8). The first service in this repo to actually write to
TimescaleDB -- every prior phase's alert/health work deliberately stood
in with a `Logging*Sink`/Redis-only path because standing up a real
Postgres schema wasn't that phase's dependency; this is where it happens.

Consumes `fusion`'s `tocsin:alerts` and `sdr_rx`'s `tocsin:health` Redis
Streams via consumer groups, upserting/inserting into Postgres and (for
alerts) fanning out live to any connected `/alerts/stream` SSE client.
Spectrum data is read straight from `sdr_rx`'s per-site
`tocsin:spectrum:<site>` Redis key on request -- no Postgres involved,
since a waterfall display only ever wants the latest snapshot, not
history (see `spectrum.py`'s docstring).

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /alerts?limit=&state=` | Recent alerts from Postgres, newest first, optionally filtered by state. |
| `GET /alerts/stream` | SSE feed of newly ingested/updated alerts, live. |
| `GET /health` | Latest RF health sample per `(site, channel)`. |
| `GET /spectrum` | Sites with a current spectrum snapshot. |
| `GET /spectrum/{site}` | Latest 48-bin spectrum snapshot for one site (404 if none yet). |
| `GET /stats` | Alert state counts and the `RF_ONLY`/`API_ONLY` divergence rate (design doc §5's stated system health metric). |

## Status

Implemented and unit tested: the Postgres schema (`schema.sql`, applied
idempotently at startup) and query functions (`db.py`), the Redis
consumer-group wiring for both inbound streams (`redis_bus.py`, async
version of the same crash-replay pattern `fusion`/`dispatcher` use, tested
against a hand-written async fake of Redis's stream semantics), the
ingestion-to-Postgres-plus-SSE-fan-out wiring (`ingest.py`), the SSE
broadcast hub (`sse.py`), the spectrum snapshot reader (`spectrum.py`),
and every REST route (`app.py`, tested via FastAPI's `TestClient` against
fake Postgres/Redis -- no real database or Redis instance in this
authoring sandbox).

**Known gaps, not yet handled:**
- No transcript storage yet -- design doc §9 lists "transcripts" alongside
  alerts/health as TimescaleDB's job, but nothing consumes
  `tocsin:transcripts` into Postgres (only `dispatcher`'s stage 2 reads
  it, ephemerally, off the stream). Worth a `transcripts` table + a third
  consumer once the UI actually wants to show transcript text.
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

## Development

```sh
uv sync
uv run pytest
```
