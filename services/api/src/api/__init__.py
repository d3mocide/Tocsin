"""api entrypoint: apply the Postgres schema, start the Redis consumer
background tasks (`tocsin:alerts` -> Postgres + SSE fan-out,
`tocsin:health` -> Postgres), and serve the FastAPI app (design doc §10
milestone 8).

`main()` does its own async setup via `asyncio.run()` and hands off to a
`uvicorn.Server` run inside that same event loop, rather than using
FastAPI's `lifespan` callback for resource construction -- see `app.py`'s
docstring for why: `create_app` takes already-built resources, which keeps
its route logic testable without needing to trigger or bypass a lifespan
context manager.
"""

from __future__ import annotations

import asyncio
import sys

from .app import create_app
from .config import ApiConfig
from .connect import PostgresStartupError, create_pool
from .db import ensure_schema
from .ingest import Ingestor
from .redis_bus import StreamConsumer
from .sse import Broadcaster

ALERTS_STREAM = "tocsin:alerts"
HEALTH_STREAM = "tocsin:health"
TRANSCRIPTS_STREAM = "tocsin:transcripts"
DISPATCHES_STREAM = "tocsin:dispatches"

STATUS_KEY = "tocsin:status:api"
STATUS_TTL_SECONDS = 30
STATUS_INTERVAL_SECONDS = 10.0


async def _heartbeat_forever(redis_client, mode: str, stop_event: asyncio.Event) -> None:
    """`api`'s own entry in `GET /services`. Async and inline rather than
    the sync `heartbeat.py` every other service carries -- this process is
    an event loop, not a polling loop, so there's no main-loop iteration to
    hang a `beat()` call on.

    Self-reporting is not circular: a client that can read `/services` at
    all has already proven `api` is up, but the row still has to be there
    or the table would show every service *except* the one serving it."""
    import json
    from datetime import datetime, timezone

    while not stop_event.is_set():
        payload = {
            "service": "api",
            "mode": mode,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "ttl_seconds": STATUS_TTL_SECONDS,
            "detail": {},
        }
        try:
            await redis_client.setex(STATUS_KEY, STATUS_TTL_SECONDS, json.dumps(payload))
        except Exception as exc:
            print(f"api: heartbeat write failed: {exc}", file=sys.stderr)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=STATUS_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass


async def _run(config: ApiConfig) -> None:
    import redis.asyncio as redis_asyncio
    import uvicorn

    pool = await create_pool(config.postgres_dsn)
    redis_client = redis_asyncio.from_url(config.redis_url, decode_responses=True)

    await ensure_schema(pool)

    broadcaster = Broadcaster()
    ingestor = Ingestor(pool, broadcaster)
    consumers = [
        StreamConsumer(redis_client, ALERTS_STREAM, ingestor.handle_alert, config.consumer_name),
        StreamConsumer(redis_client, HEALTH_STREAM, ingestor.handle_health, config.consumer_name),
        StreamConsumer(redis_client, TRANSCRIPTS_STREAM, ingestor.handle_transcript, config.consumer_name),
        StreamConsumer(redis_client, DISPATCHES_STREAM, ingestor.handle_dispatch, config.consumer_name),
    ]
    for consumer in consumers:
        await consumer.start()

    stop_event = asyncio.Event()
    background_tasks = [asyncio.create_task(consumer.run_forever(stop_event)) for consumer in consumers]
    background_tasks.append(asyncio.create_task(_heartbeat_forever(redis_client, config.mode, stop_event)))

    app = create_app(pool, redis_client, broadcaster, static_dir=config.static_dir, config=config)
    server = uvicorn.Server(uvicorn.Config(app, host=config.host, port=config.port, log_level="info"))
    print(f"api: serving on {config.host}:{config.port}, Postgres + Redis connected", flush=True)
    try:
        await server.serve()
    finally:
        stop_event.set()
        for task in background_tasks:
            task.cancel()
        await pool.close()
        await redis_client.close()


def main() -> None:
    config = ApiConfig.from_env()
    if not config.postgres_dsn:
        print(
            "api: no Postgres connection configured -- set API_POSTGRES_PASSWORD "
            "(compose passes POSTGRES_PASSWORD through) or API_POSTGRES_DSN. Refusing to start.",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        asyncio.run(_run(config))
    except PostgresStartupError as exc:
        # One legible block instead of an asyncpg traceback repeated every
        # few seconds by `restart: on-failure` -- nothing about these is
        # fixable by retrying, and the restart loop is what hid the
        # explanation in the first place.
        print(exc, file=sys.stderr, flush=True)
        sys.exit(1)
