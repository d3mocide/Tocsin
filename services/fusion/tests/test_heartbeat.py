"""Covers the `heartbeat.py` every service carries a copy of (CLAUDE.md:
no cross-service imports, so the module is duplicated per service). Tested
once, here, rather than eight identical times -- the copies are generated
from the same source and differ only in `SERVICE_NAME`."""

import json

from fusion.heartbeat import DEFAULT_TTL_SECONDS, Heartbeat, build


class FakeRedis:
    def __init__(self, fail=False):
        self.setex_calls = []
        self.fail = fail

    def setex(self, key, ttl, value):
        if self.fail:
            raise ConnectionError("redis is gone")
        self.setex_calls.append((key, ttl, value))


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_first_beat_writes_immediately():
    redis = FakeRedis()
    Heartbeat(redis, clock=FakeClock()).beat()

    key, ttl, raw = redis.setex_calls[0]
    assert key == "tocsin:status:fusion"
    assert ttl == DEFAULT_TTL_SECONDS
    assert json.loads(raw)["service"] == "fusion"


def test_the_key_expires_so_a_dead_service_cannot_look_healthy():
    """The TTL is the entire mechanism -- a crashed process stops writing
    and its key disappears, which is what makes absence mean 'down'."""
    redis = FakeRedis()
    Heartbeat(redis, ttl_seconds=30, interval_seconds=10, clock=FakeClock()).beat()

    _key, ttl, _raw = redis.setex_calls[0]
    assert ttl == 30
    # 3x the write interval: one missed write must not flap the board.
    assert ttl == 3 * 10


def test_beat_throttles_to_the_interval():
    """Called unconditionally from a main loop that may spin at 1 Hz --
    without self-throttling this would hammer Redis."""
    clock = FakeClock()
    redis = FakeRedis()
    heartbeat = Heartbeat(redis, interval_seconds=10.0, clock=clock)

    assert heartbeat.beat() is True
    clock.now = 5.0
    assert heartbeat.beat() is False
    clock.now = 10.0
    assert heartbeat.beat() is True

    assert len(redis.setex_calls) == 2


def test_detail_kwargs_ride_along():
    redis = FakeRedis()
    Heartbeat(redis, clock=FakeClock()).beat(mode="hybrid", sites=["home"])

    payload = json.loads(redis.setex_calls[0][2])
    assert payload["detail"] == {"mode": "hybrid", "sites": ["home"]}


def test_a_redis_failure_is_swallowed_not_raised():
    """This module reports liveness; it must never be the thing that ends
    it. A Redis blip taking down fusion would be exactly backwards."""
    heartbeat = Heartbeat(FakeRedis(fail=True), clock=FakeClock())

    assert heartbeat.beat() is False  # did not raise


def test_a_failed_write_retries_on_the_next_interval_not_sooner():
    """A failed write is not retried early. That's deliberate rather than
    incidental: the TTL is 3x the interval, so a single failure still
    leaves the key alive until the next scheduled beat, and retrying in a
    tight loop against a Redis that just refused a write would make an
    outage worse for no gain in reporting accuracy."""
    clock = FakeClock()
    redis = FakeRedis(fail=True)
    heartbeat = Heartbeat(redis, interval_seconds=10.0, clock=clock)

    assert heartbeat.beat() is False  # failed
    redis.fail = False

    clock.now = 5.0
    assert heartbeat.beat() is False  # still throttled, not retried early
    assert redis.setex_calls == []

    clock.now = 10.0
    assert heartbeat.beat() is True
    assert len(redis.setex_calls) == 1


def test_build_returns_none_without_a_redis_client():
    assert build(None) is None
    assert isinstance(build(FakeRedis()), Heartbeat)
