import json
from datetime import datetime, timedelta, timezone

from api import status


class FakeRedis:
    def __init__(self, store=None):
        self.store = store or {}

    async def keys(self, pattern):
        prefix = pattern.rstrip("*")
        return [k for k in self.store if k.startswith(prefix)]

    async def get(self, key):
        return self.store.get(key)


def _beat(service, updated_at=None, detail=None):
    return json.dumps(
        {
            "service": service,
            "updated_at": (updated_at or datetime.now(timezone.utc)).isoformat(),
            "ttl_seconds": 30,
            "detail": detail or {},
        }
    )


def test_offgrid_does_not_expect_the_hybrid_only_poller():
    """nws_poller only runs under hybrid (design doc §8) -- reporting it
    down offgrid would be a permanent false alarm on exactly the
    deployment that has to work with no network."""
    assert "nws_poller" not in status.expected_services("offgrid")
    assert "nws_poller" in status.expected_services("hybrid")


def test_unknown_mode_is_treated_as_offgrid():
    assert "nws_poller" not in status.expected_services(None)


async def test_a_service_with_no_heartbeat_is_reported_down_not_omitted():
    """The whole point of the expected-set comparison: a crashed service
    writes nothing, so listing only present keys would render it as absent
    from the table rather than broken."""
    redis = FakeRedis({f"tocsin:status:{name}": _beat(name) for name in status.EXPECTED_ALWAYS})
    del redis.store["tocsin:status:dispatcher"]

    rows = await status.list_services(redis, mode="offgrid")

    by_service = {row["service"]: row for row in rows}
    assert by_service["dispatcher"]["status"] == status.STATUS_DOWN
    assert by_service["dispatcher"]["expected"] is True
    assert by_service["fusion"]["status"] == status.STATUS_UP


async def test_every_expected_service_appears_even_with_an_empty_redis():
    rows = await status.list_services(FakeRedis(), mode="hybrid")

    assert {row["service"] for row in rows} == set(status.expected_services("hybrid"))
    assert all(row["status"] == status.STATUS_DOWN for row in rows)


async def test_an_unrecognized_heartbeat_is_surfaced_not_hidden():
    redis = FakeRedis({"tocsin:status:mystery": _beat("mystery")})

    rows = await status.list_services(redis, mode="offgrid")

    mystery = next(row for row in rows if row["service"] == "mystery")
    assert mystery["status"] == status.STATUS_UNEXPECTED
    assert mystery["expected"] is False


async def test_detail_and_age_are_carried_through():
    stale = datetime.now(timezone.utc) - timedelta(seconds=12)
    redis = FakeRedis({"tocsin:status:fusion": _beat("fusion", updated_at=stale, detail={"mode": "hybrid"})})

    rows = await status.list_services(redis, mode="offgrid")

    fusion = next(row for row in rows if row["service"] == "fusion")
    assert fusion["detail"] == {"mode": "hybrid"}
    assert 10 <= fusion["age_seconds"] <= 20


async def test_a_key_that_expires_between_keys_and_get_is_not_an_error():
    """A 30s TTL means KEYS can legitimately return a key that GET no
    longer finds. That's a late service, not a crash -- and definitely not
    a 500."""

    class RacingRedis(FakeRedis):
        async def get(self, key):
            return None

    rows = await status.list_services(RacingRedis({"tocsin:status:fusion": _beat("fusion")}), mode="offgrid")

    fusion = next(row for row in rows if row["service"] == "fusion")
    assert fusion["status"] == status.STATUS_DOWN


async def test_malformed_heartbeat_json_is_skipped_rather_than_raising():
    redis = FakeRedis({"tocsin:status:fusion": "not json"})

    rows = await status.list_services(redis, mode="offgrid")

    fusion = next(row for row in rows if row["service"] == "fusion")
    assert fusion["status"] == status.STATUS_DOWN
