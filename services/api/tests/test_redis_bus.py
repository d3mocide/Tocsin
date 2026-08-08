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


async def test_run_forever_stops_when_the_event_is_set():
    redis = FakeAsyncRedisStreams()
    consumer = StreamConsumer(redis, STREAM, lambda payload: None, "api-test")
    await consumer.start()

    stop_event = asyncio.Event()
    stop_event.set()
    await asyncio.wait_for(consumer.run_forever(stop_event), timeout=1.0)  # returns immediately
