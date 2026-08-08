"""Consumes canonical Alerts (`tocsin:alerts`) and RF health samples
(`tocsin:health`) via Redis consumer groups -- same durability pattern as
`fusion.redis_bus`/`dispatcher.redis_bus` ("at least once," not "exactly
once"). A redelivered duplicate is harmless on both streams here (unlike
dispatcher's mesh sends): `db.upsert_alert` is idempotent by `id`, and one
duplicate health sample is a harmless blip in a time series, not a
double-charged mesh message. Not a shared import from `fusion`/`sdr_rx` --
service boundary (CLAUDE.md).

Async, unlike the sync versions in `fusion`/`dispatcher`: `api` is a
FastAPI/uvicorn process, not a blocking polling loop, so this uses
`redis.asyncio` throughout and `asyncio.create_task` for the background
consume loop rather than a synchronous `while True`.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Awaitable, Callable

GROUP_NAME = "api"


async def ensure_group(redis_client, stream: str, group: str = GROUP_NAME) -> None:
    try:
        await redis_client.xgroup_create(stream, group, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


class StreamConsumer:
    def __init__(
        self,
        redis_client,
        stream: str,
        handler: Callable[[dict], Awaitable[None]],
        consumer_name: str,
        group: str = GROUP_NAME,
        count: int = 100,
    ):
        self._redis = redis_client
        self._stream = stream
        self._handler = handler
        self._consumer_name = consumer_name
        self._group = group
        self._count = count

    async def start(self) -> None:
        """Creates the consumer group and replays this consumer's own
        still-pending entries from a prior crash (Redis's `"0"` read-id) --
        must be awaited once before `poll_once`/`run_forever`."""
        await ensure_group(self._redis, self._stream, self._group)
        await self._read_and_handle("0", block_ms=None)

    async def poll_once(self, block_ms: int = 1000) -> int:
        return await self._read_and_handle(">", block_ms=block_ms)

    async def _read_and_handle(self, read_id: str, block_ms: int | None) -> int:
        kwargs = {"count": self._count}
        if block_ms is not None:
            kwargs["block"] = block_ms
        response = await self._redis.xreadgroup(self._group, self._consumer_name, {self._stream: read_id}, **kwargs)
        if not response:
            return 0
        processed = 0
        for _stream_name, entries in response:
            for entry_id, fields in entries:
                await self._handler(json.loads(fields["payload"]))
                await self._redis.xack(self._stream, self._group, entry_id)
                processed += 1
        return processed

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await self.poll_once()
            except Exception as exc:
                # A single bad poll cycle must not kill the background
                # task -- same posture as every other service's main loop.
                print(f"api: poll cycle failed on {self._stream}: {exc}", file=sys.stderr)
                await asyncio.sleep(1.0)
