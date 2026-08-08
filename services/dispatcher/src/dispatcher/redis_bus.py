"""Consumes canonical Alerts from `tocsin:alerts` via a Redis consumer
group -- same durability pattern as `fusion.redis_bus` ("at least once,"
not "exactly once"; a crash between processing and acking can replay one
alert on restart, which `idempotency.py`'s Redis-persisted claim is
specifically there to make safe to do). Not a shared import from `fusion`
-- service boundary (CLAUDE.md); the stream name and payload shape here
duplicate what `fusion.redis_sink` publishes.
"""

from __future__ import annotations

import json
from typing import Callable

STREAM_NAME = "tocsin:alerts"
GROUP_NAME = "dispatcher"


def ensure_group(redis_client, stream: str = STREAM_NAME, group: str = GROUP_NAME) -> None:
    try:
        redis_client.xgroup_create(stream, group, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


class AlertStreamConsumer:
    def __init__(
        self,
        redis_client,
        handler: Callable[[dict], None],
        consumer_name: str,
        stream: str = STREAM_NAME,
        group: str = GROUP_NAME,
        count: int = 100,
    ):
        self._redis = redis_client
        self._handler = handler
        self._consumer_name = consumer_name
        self._stream = stream
        self._group = group
        self._count = count
        ensure_group(self._redis, stream, group)
        # Replays this consumer's own still-pending entries from a prior
        # crash before reading anything new -- see fusion.redis_bus's
        # identical mechanism for the full reasoning.
        self._read_and_handle("0", block_ms=None)

    def poll_once(self, block_ms: int = 1000) -> int:
        return self._read_and_handle(">", block_ms=block_ms)

    def _read_and_handle(self, read_id: str, block_ms: int | None) -> int:
        kwargs = {"count": self._count}
        if block_ms is not None:
            kwargs["block"] = block_ms
        response = self._redis.xreadgroup(self._group, self._consumer_name, {self._stream: read_id}, **kwargs)
        if not response:
            return 0
        processed = 0
        for _stream_name, entries in response:
            for entry_id, fields in entries:
                self._handler(json.loads(fields["payload"]))
                self._redis.xack(self._stream, self._group, entry_id)
                processed += 1
        return processed
