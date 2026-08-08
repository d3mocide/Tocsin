"""Wires the Redis consumers (`redis_bus.py`) to Postgres writes (`db.py`)
and fans newly ingested records out to any connected SSE clients
(`sse.py`) -- one place where "durable store" and "live feed" meet, so a
client watching `/events` sees exactly what's also landing in Postgres,
not a separately-derived view.
"""

from __future__ import annotations

from . import db, sse
from .sse import Broadcaster


class Ingestor:
    def __init__(self, pool: db.PoolLike, broadcaster: Broadcaster):
        self._pool = pool
        self._broadcaster = broadcaster

    async def handle_alert(self, payload: dict) -> None:
        await db.upsert_alert(self._pool, payload)
        await self._broadcaster.publish(sse.EVENT_ALERT, payload)

    async def handle_health(self, payload: dict) -> None:
        await db.insert_health_sample(self._pool, payload)
        # Pushed as well as stored, unlike before: the UI's channel table
        # used to poll for this every 5s, which meant a channel going dead
        # (design doc §3's primary liveness signal for the whole SDR path)
        # could sit unrendered for those 5s. It now reaches the screen on
        # the same sample that wrote it.
        await self._broadcaster.publish(sse.EVENT_HEALTH, payload)

    async def handle_transcript(self, payload: dict) -> None:
        await db.insert_transcript(self._pool, payload)
        await self._broadcaster.publish(sse.EVENT_TRANSCRIPT, payload)

    async def handle_dispatch(self, payload: dict) -> None:
        await db.insert_dispatch(self._pool, payload)
        await self._broadcaster.publish(sse.EVENT_DISPATCH, payload)
