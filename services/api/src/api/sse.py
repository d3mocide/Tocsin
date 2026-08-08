"""In-process broadcast hub for the `/alerts/stream` SSE endpoint
(design doc §10 milestone 8: "FastAPI REST + SSE feed"): each connected
client gets its own `asyncio.Queue`; `publish()` fans one alert out to
every currently-connected queue.

Deliberately in-process, not Redis pub/sub -- `api` is a single-process
FastAPI app with no horizontal-scaling story yet, so there's no second
process that would need to observe these events, and Redis pub/sub would
be strictly more moving parts for the same result.
"""

from __future__ import annotations

import asyncio


class Broadcaster:
    def __init__(self):
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> "asyncio.Queue[dict]":
        queue: "asyncio.Queue[dict]" = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: "asyncio.Queue[dict]") -> None:
        self._subscribers.discard(queue)

    async def publish(self, item: dict) -> None:
        for queue in list(self._subscribers):
            await queue.put(item)
