"""Wires the Redis consumers (`redis_bus.py`) to Postgres writes (`db.py`)
and fans newly ingested alerts out to any connected SSE clients
(`sse.py`) -- one place where "durable store" and "live feed" meet, so a
client watching `/alerts/stream` sees exactly what's also landing in
Postgres, not a separately-derived view.
"""

from __future__ import annotations

from . import db
from .sse import Broadcaster


class Ingestor:
    def __init__(self, pool: db.PoolLike, broadcaster: Broadcaster):
        self._pool = pool
        self._broadcaster = broadcaster

    async def handle_alert(self, payload: dict) -> None:
        await db.upsert_alert(self._pool, payload)
        await self._broadcaster.publish(payload)

    async def handle_health(self, payload: dict) -> None:
        await db.insert_health_sample(self._pool, payload)
