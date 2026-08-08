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
from .db import ensure_schema
from .ingest import Ingestor
from .redis_bus import StreamConsumer
from .sse import Broadcaster

ALERTS_STREAM = "tocsin:alerts"
HEALTH_STREAM = "tocsin:health"


async def _run(config: ApiConfig) -> None:
    import asyncpg
    import redis.asyncio as redis_asyncio
    import uvicorn

    pool = await asyncpg.create_pool(dsn=config.postgres_dsn)
    redis_client = redis_asyncio.from_url(config.redis_url, decode_responses=True)

    await ensure_schema(pool)

    broadcaster = Broadcaster()
    ingestor = Ingestor(pool, broadcaster)
    alerts_consumer = StreamConsumer(redis_client, ALERTS_STREAM, ingestor.handle_alert, config.consumer_name)
    health_consumer = StreamConsumer(redis_client, HEALTH_STREAM, ingestor.handle_health, config.consumer_name)
    await alerts_consumer.start()
    await health_consumer.start()

    stop_event = asyncio.Event()
    background_tasks = [
        asyncio.create_task(alerts_consumer.run_forever(stop_event)),
        asyncio.create_task(health_consumer.run_forever(stop_event)),
    ]

    app = create_app(pool, redis_client, broadcaster, static_dir=config.static_dir)
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
        print("api: API_POSTGRES_DSN is required -- refusing to start", file=sys.stderr)
        sys.exit(1)
    asyncio.run(_run(config))
