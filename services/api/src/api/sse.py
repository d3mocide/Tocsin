"""In-process broadcast hub for the `/events` SSE stream (design doc §10
milestone 8: "FastAPI REST + SSE feed"): each connected client gets its
own `asyncio.Queue`; `publish()` fans one message out to every currently-
connected queue.

Messages are *named* SSE events (`event: alert`, `event: health`, ...)
rather than a single anonymous stream. One connection now carries
everything the page updates on, which is what let the frontend drop its
polling timers for health/stats -- an SSE stream the browser already holds
open is strictly cheaper than a `setInterval` re-fetching state that
usually hasn't changed, and it also means a channel going dead reaches the
screen when it happens rather than up to five seconds later.

Deliberately in-process, not Redis pub/sub -- `api` is a single-process
FastAPI app with no horizontal-scaling story yet, so there's no second
process that would need to observe these events, and Redis pub/sub would
be strictly more moving parts for the same result.
"""

from __future__ import annotations

import asyncio
import json

EVENT_ALERT = "alert"
EVENT_HEALTH = "health"
EVENT_STATS = "stats"
EVENT_TRANSCRIPT = "transcript"
EVENT_DISPATCH = "dispatch"

# Bounded so one stalled client (a laptop asleep with the tab open, a
# browser throttling a background tab) cannot grow its queue without limit
# and take the process's memory with it. On overflow the *oldest* message
# is dropped rather than the newest: a client that has fallen behind wants
# current state, not a backlog it will render and immediately replace.
DEFAULT_MAX_QUEUE = 256


class Broadcaster:
    def __init__(self, max_queue: int = DEFAULT_MAX_QUEUE):
        self._subscribers: set[asyncio.Queue] = set()
        self._max_queue = max_queue

    def subscribe(self) -> "asyncio.Queue[tuple[str, dict]]":
        queue: "asyncio.Queue[tuple[str, dict]]" = asyncio.Queue(maxsize=self._max_queue)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: "asyncio.Queue[tuple[str, dict]]") -> None:
        self._subscribers.discard(queue)

    async def publish(self, event: str, item: dict) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait((event, item))
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait((event, item))
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    # Raced with the client's own consumer; it is keeping
                    # up after all, so dropping this one message is fine.
                    pass

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


def format_sse(event: str, item: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(item, default=str)}\n\n"
