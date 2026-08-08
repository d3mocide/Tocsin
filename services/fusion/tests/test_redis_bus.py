import json

import pytest

from fusion.mapping import EventMapping
from fusion.models import AlertState
from fusion.redis_bus import CAP_STREAM, GROUP_NAME, SAME_STREAM, StreamConsumer, ensure_group
from fusion.store import AlertStore

from fake_redis_streams import FakeRedisStreams

MAPPING = EventMapping({"TOR": "Tornado Warning"})


def _same_payload(**overrides) -> dict:
    payload = {
        "site": "home",
        "channel": "WX5",
        "timestamp_ns": 1_786_224_720_000_000_000,  # 2026-08-08T21:32:00Z
        "event_code": "TOR",
        "event_name": "Tornado Warning",
        "tier": "A",
        "fips_codes": ["041051"],
        "originator": "WXR",
        "callsign": "KPQR/NWS",
        "purge_minutes": 45,
        "raw_header": "ZCZC-WXR-TOR-041051+0045-2202132-KPQR/NWS-",
    }
    payload.update(overrides)
    return payload


def _cap_payload(**overrides) -> dict:
    payload = {
        "id": "urn:oid:2.49.0.1.840.0.example",
        "event": "Tornado Warning",
        "headline": "Tornado Warning issued",
        "status": "Actual",
        "message_type": "Alert",
        "category": "Met",
        "severity": "Extreme",
        "certainty": "Observed",
        "urgency": "Immediate",
        "area_desc": "Multnomah, OR",
        "sent": "2026-08-08T21:32:00+00:00",
        "effective": "2026-08-08T21:32:00+00:00",
        "onset": "2026-08-08T21:32:00+00:00",
        "expires": "2026-08-08T22:32:00+00:00",
        "ends": "2026-08-08T22:32:00+00:00",
        "same_codes": ["041051"],
        "ugc_codes": ["ORZ006"],
        "vtec": None,
    }
    payload.update(overrides)
    return payload


def _store():
    return AlertStore(MAPPING, "hybrid")


def test_ensure_group_tolerates_a_second_call():
    redis = FakeRedisStreams()
    ensure_group(redis, SAME_STREAM)
    ensure_group(redis, SAME_STREAM)  # must not raise (BUSYGROUP)


def test_ensure_group_reraises_non_busygroup_errors():
    class ExplodingRedis(FakeRedisStreams):
        def xgroup_create(self, *a, **k):
            raise Exception("connection refused")

    with pytest.raises(Exception, match="connection refused"):
        ensure_group(ExplodingRedis(), SAME_STREAM)


def test_new_same_event_is_ingested_and_acked():
    redis = FakeRedisStreams()
    redis.xadd(SAME_STREAM, {"payload": json.dumps(_same_payload())})
    store = _store()
    consumer = StreamConsumer(redis, store, "fusion-test")

    processed = consumer.poll_once(block_ms=None)

    assert processed == 1
    assert len(store.all_alerts) == 1
    assert store.all_alerts[0].state == AlertState.RF_ONLY
    # fully acked -- nothing left pending for this consumer
    assert redis.xreadgroup(GROUP_NAME, "fusion-test", {SAME_STREAM: "0"}) == []


def test_new_cap_alert_is_ingested_and_acked():
    redis = FakeRedisStreams()
    redis.xadd(CAP_STREAM, {"payload": json.dumps(_cap_payload())})
    store = _store()
    consumer = StreamConsumer(redis, store, "fusion-test")

    processed = consumer.poll_once(block_ms=None)

    assert processed == 1
    assert store.all_alerts[0].state == AlertState.API_ONLY


def test_matching_events_across_both_streams_confirm_one_alert():
    redis = FakeRedisStreams()
    redis.xadd(SAME_STREAM, {"payload": json.dumps(_same_payload())})
    redis.xadd(
        CAP_STREAM,
        {"payload": json.dumps(_cap_payload(sent="2026-08-08T21:32:00+00:00"))},
    )
    store = _store()
    consumer = StreamConsumer(redis, store, "fusion-test")

    consumer.poll_once(block_ms=None)

    assert len(store.all_alerts) == 1
    assert store.all_alerts[0].state == AlertState.CONFIRMED


def test_crash_before_ack_is_replayed_on_reconnect_with_the_same_consumer_name():
    redis = FakeRedisStreams()
    redis.xadd(SAME_STREAM, {"payload": json.dumps(_same_payload())})
    store1 = _store()
    consumer1 = StreamConsumer(redis, store1, "fusion-test")
    consumer1._handle_same = lambda payload: (_ for _ in ()).throw(RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        consumer1.poll_once(block_ms=None)
    # delivered but never acked -- store1 never actually recorded it either
    assert store1.all_alerts == ()

    store2 = _store()
    consumer2 = StreamConsumer(redis, store2, "fusion-test")  # same consumer name -> replay on init

    assert len(store2.all_alerts) == 1
    assert store2.all_alerts[0].state == AlertState.RF_ONLY


def test_a_different_consumer_name_does_not_see_another_consumers_pending_entries():
    redis = FakeRedisStreams()
    redis.xadd(SAME_STREAM, {"payload": json.dumps(_same_payload())})
    store1 = _store()
    consumer1 = StreamConsumer(redis, store1, "fusion-a")
    consumer1._handle_same = lambda payload: (_ for _ in ()).throw(RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        consumer1.poll_once(block_ms=None)

    store2 = _store()
    StreamConsumer(redis, store2, "fusion-b")  # a different consumer name

    assert store2.all_alerts == ()
