import json

import pytest

from dispatcher.redis_bus import AlertStreamConsumer, GROUP_NAME, STREAM_NAME, ensure_group

from fake_redis_streams import FakeRedisStreams


def _payload(**overrides):
    payload = {"id": "abc123", "state": "RF_ONLY", "sources": []}
    payload.update(overrides)
    return payload


def test_ensure_group_tolerates_a_second_call():
    redis = FakeRedisStreams()
    ensure_group(redis, STREAM_NAME)
    ensure_group(redis, STREAM_NAME)


def test_ensure_group_reraises_non_busygroup_errors():
    class ExplodingRedis(FakeRedisStreams):
        def xgroup_create(self, *a, **k):
            raise Exception("connection refused")

    with pytest.raises(Exception, match="connection refused"):
        ensure_group(ExplodingRedis(), STREAM_NAME)


def test_new_entry_is_handled_and_acked():
    redis = FakeRedisStreams()
    redis.xadd(STREAM_NAME, {"payload": json.dumps(_payload())})
    received = []
    consumer = AlertStreamConsumer(redis, received.append, "dispatcher-test")

    processed = consumer.poll_once(block_ms=None)

    assert processed == 1
    assert received == [_payload()]
    assert redis.xreadgroup(GROUP_NAME, "dispatcher-test", {STREAM_NAME: "0"}) == []


def test_crash_before_handling_completes_is_replayed_on_reconnect():
    redis = FakeRedisStreams()
    redis.xadd(STREAM_NAME, {"payload": json.dumps(_payload())})

    def boom(payload):
        raise RuntimeError("boom")

    consumer1 = AlertStreamConsumer(redis, boom, "dispatcher-test")
    with pytest.raises(RuntimeError):
        consumer1.poll_once(block_ms=None)

    received = []
    AlertStreamConsumer(redis, received.append, "dispatcher-test")  # same consumer name -> replay

    assert received == [_payload()]
