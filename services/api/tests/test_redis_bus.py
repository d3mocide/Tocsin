import asyncio
import json

import pytest

from api.redis_bus import GROUP_NAME, StreamConsumer, ensure_group

from fake_redis_streams import FakeAsyncRedisStreams

STREAM = "tocsin:alerts"


async def test_ensure_group_tolerates_a_second_call():
    redis = FakeAsyncRedisStreams()
    await ensure_group(redis, STREAM)
    await ensure_group(redis, STREAM)


async def test_ensure_group_reraises_non_busygroup_errors():
    class ExplodingRedis(FakeAsyncRedisStreams):
        async def xgroup_create(self, *a, **k):
            raise Exception("connection refused")

    with pytest.raises(Exception, match="connection refused"):
        await ensure_group(ExplodingRedis(), STREAM)


async def test_new_entry_is_handled_and_acked():
    redis = FakeAsyncRedisStreams()
    await redis.xadd(STREAM, {"payload": json.dumps({"id": "a1"})})
    received = []

    async def handler(payload):
        received.append(payload)

    consumer = StreamConsumer(redis, STREAM, handler, "api-test")
    await consumer.start()

    processed = await consumer.poll_once(block_ms=None)

    assert processed == 1
    assert received == [{"id": "a1"}]
    assert await redis.xreadgroup(GROUP_NAME, "api-test", {STREAM: "0"}) == []


async def test_crash_before_ack_is_replayed_on_reconnect():
    redis = FakeAsyncRedisStreams()
    await redis.xadd(STREAM, {"payload": json.dumps({"id": "a1"})})

    async def boom(payload):
        raise RuntimeError("boom")

    consumer1 = StreamConsumer(redis, STREAM, boom, "api-test")
    await consumer1.start()
    with pytest.raises(RuntimeError):
        await consumer1.poll_once(block_ms=None)

    received = []

    async def handler(payload):
        received.append(payload)

    consumer2 = StreamConsumer(redis, STREAM, handler, "api-test")  # same consumer name -> replay
    await consumer2.start()

    assert received == [{"id": "a1"}]


async def test_multiple_entries_are_acked_in_one_batched_call():
    """Regression test for the fix in docs/design/tracking.md's 2026-08-09
    entry: xreadgroup already reads a whole batch in one round trip, so
    acking one entry at a time threw that batching away on the write side --
    a real cost at sdr_rx's health-sample volume."""
    redis = FakeAsyncRedisStreams()
    await redis.xadd(STREAM, {"payload": json.dumps({"id": "a1"})})
    await redis.xadd(STREAM, {"payload": json.dumps({"id": "a2"})})
    await redis.xadd(STREAM, {"payload": json.dumps({"id": "a3"})})

    ack_calls = []
    original_xack = redis.xack

    async def spy_xack(stream, group, *ids):
        ack_calls.append(ids)
        return await original_xack(stream, group, *ids)

    redis.xack = spy_xack

    received = []

    async def handler(payload):
        received.append(payload)

    consumer = StreamConsumer(redis, STREAM, handler, "api-test")
    await consumer.start()
    processed = await consumer.poll_once(block_ms=None)

    assert processed == 3
    assert len(received) == 3
    assert len(ack_calls) == 1  # one XACK call for the whole batch...
    assert set(ack_calls[0]) == {"1-0", "2-0", "3-0"}  # ...covering every entry


async def test_entries_before_a_mid_batch_failure_are_still_acked():
    """Batching the ack must not weaken the existing at-least-once
    guarantee: whatever succeeded before a handler raised stays acked
    (not replayed) exactly as it did with the old per-entry ack, and only
    the entry that failed (plus anything after it, never reached) stays
    pending."""
    redis = FakeAsyncRedisStreams()
    await redis.xadd(STREAM, {"payload": json.dumps({"id": "a1"})})
    await redis.xadd(STREAM, {"payload": json.dumps({"id": "a2"})})

    async def handler(payload):
        if payload["id"] == "a2":
            raise RuntimeError("boom")

    consumer = StreamConsumer(redis, STREAM, handler, "api-test")
    await consumer.start()
    with pytest.raises(RuntimeError):
        await consumer.poll_once(block_ms=None)

    pending = await redis.xreadgroup(GROUP_NAME, "api-test", {STREAM: "0"})
    pending_ids = {entry_id for _stream, entries in pending for entry_id, _fields in entries}
    assert pending_ids == {"2-0"}  # a1 was acked; only a2 remains for replay


async def test_run_forever_stops_when_the_event_is_set():
    redis = FakeAsyncRedisStreams()
    consumer = StreamConsumer(redis, STREAM, lambda payload: None, "api-test")
    await consumer.start()

    stop_event = asyncio.Event()
    stop_event.set()
    await asyncio.wait_for(consumer.run_forever(stop_event), timeout=1.0)  # returns immediately
