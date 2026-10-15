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
from collections import deque

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

# Events worth replaying to a client that reconnects with `Last-Event-ID`: the rare ones a consumer must not
# miss. Health samples arrive many times a second and are only ever useful live.
REPLAYED_EVENTS = frozenset({EVENT_ALERT, EVENT_TRANSCRIPT, EVENT_DISPATCH})
DEFAULT_HISTORY = 200


class Message(tuple):
    """`(event, item)`, equal to that plain tuple, that also carries its SSE `id` for `Last-Event-ID` replay."""

    id: int

    def __new__(cls, event: str, item: dict, id: int) -> "Message":
        message = super().__new__(cls, (event, item))
        message.id = id
        return message


class Broadcaster:
    def __init__(self, max_queue: int = DEFAULT_MAX_QUEUE, history: int = DEFAULT_HISTORY):
        self._subscribers: set[asyncio.Queue] = set()
        self._max_queue = max_queue
        self._seq = 0
        self._history: "deque[tuple[int, str, dict]]" = deque(maxlen=history)

    def subscribe(self, last_event_id: int | None = None) -> "asyncio.Queue[Message]":
        """Queue of `Message`s (`(event, item)` tuples with an `.id`). With `last_event_id`, the replayable events published after that id
        are queued first (those still in the history; older ones are gone)."""
        queue: "asyncio.Queue[Message]" = asyncio.Queue(maxsize=self._max_queue)
        if last_event_id is not None:
            for seq, event, item in self._history:
                if seq > last_event_id:
                    queue.put_nowait(Message(event, item, seq))
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: "asyncio.Queue[Message]") -> None:
        self._subscribers.discard(queue)

    async def publish(self, event: str, item: dict) -> None:
        self._seq += 1
        if event in REPLAYED_EVENTS:
            self._history.append((self._seq, event, item))
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(Message(event, item, self._seq))
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(Message(event, item, self._seq))
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    # Raced with the client's own consumer; it is keeping
                    # up after all, so dropping this one message is fine.
                    pass

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


def format_sse(event: str, item: dict, event_id: int | None = None) -> str:
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    return f"{prefix}event: {event}\ndata: {json.dumps(item, default=str)}\n\n"
