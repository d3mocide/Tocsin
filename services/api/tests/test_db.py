from datetime import datetime
import json
from pathlib import Path

from api import db

from fake_pool import FakePool


def _alert(**overrides):
    alert = {
        "id": "abc123",
        "state": "RF_ONLY",
        "confidence": 0.6,
        "event_name": "Tornado Warning",
        "fips_codes": ["041051"],
        "first_seen": "2026-08-08T21:00:00+00:00",
        "last_updated": "2026-08-08T21:00:00+00:00",
        "sources": [{"kind": "RF", "event": {"event_code": "TOR"}}],
    }
    alert.update(overrides)
    return alert


def _health(**overrides):
    health = {
        "site": "home",
        "channel": "WX5",
        "timestamp_ns": 1_786_224_720_000_000_000,
        "rms": 0.1,
        "power": 0.01,
        "dead": False,
    }
    health.update(overrides)
    return health


async def test_ensure_schema_executes_every_statement(tmp_path):
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text("CREATE TABLE a (x int);\nCREATE TABLE b (y int);")
    pool = FakePool()

    await db.ensure_schema(pool, schema_path=schema_file)

    assert len(pool.executed) == 2
    assert "CREATE TABLE a" in pool.executed[0][0]
    assert "CREATE TABLE b" in pool.executed[1][0]


async def test_ensure_schema_skips_blank_statements(tmp_path):
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text("CREATE TABLE a (x int);\n\n   \n;")
    pool = FakePool()

    await db.ensure_schema(pool, schema_path=schema_file)

    assert len(pool.executed) == 1


async def test_upsert_alert_converts_iso_timestamps_to_datetime():
    pool = FakePool()
    await db.upsert_alert(pool, _alert())

    _query, args = pool.executed[0]
    from datetime import datetime

    assert isinstance(args[5], datetime)  # first_seen
    assert isinstance(args[6], datetime)  # last_updated


async def test_upsert_alert_serializes_sources_as_json():
    pool = FakePool()
    await db.upsert_alert(pool, _alert())

    _query, args = pool.executed[0]
    assert json.loads(args[7]) == _alert()["sources"]


async def test_insert_health_sample_passes_nanosecond_timestamp_through():
    pool = FakePool()
    await db.insert_health_sample(pool, _health())

    _query, args = pool.executed[0]
    assert args[0] == "home"
    assert args[1] == "WX5"
    assert args[2] == 1_786_224_720_000_000_000


async def test_list_alerts_without_state_filter_uses_the_unfiltered_query():
    pool = FakePool(fetch_results=[[{"id": "a1", "sources": json.dumps([{"kind": "RF"}])}]])
    rows = await db.list_alerts(pool, limit=50)

    assert "WHERE" not in pool.fetch_calls[0][0]
    assert pool.fetch_calls[0][1] == (50,)
    assert rows[0]["sources"] == [{"kind": "RF"}]  # JSON string decoded back into a list


async def test_list_alerts_with_state_filter_uses_the_filtered_query():
    pool = FakePool(fetch_results=[[]])
    await db.list_alerts(pool, limit=10, state="CONFIRMED")

    query, args = pool.fetch_calls[0]
    assert "WHERE state = $1" in query
    assert args == ("CONFIRMED", 10)


async def test_latest_health_uses_distinct_on_site_channel():
    pool = FakePool(fetch_results=[[{"site": "home", "channel": "WX5", "dead": False}]])
    rows = await db.latest_health(pool)

    assert "DISTINCT ON (site, channel)" in pool.fetch_calls[0][0]
    assert rows == [{"site": "home", "channel": "WX5", "dead": False}]


async def test_alert_state_counts_returns_a_plain_dict():
    pool = FakePool(fetch_results=[[{"state": "RF_ONLY", "count": 3}, {"state": "CONFIRMED", "count": 7}]])
    counts = await db.alert_state_counts(pool)
    assert counts == {"RF_ONLY": 3, "CONFIRMED": 7}


async def test_insert_transcript_is_idempotent_on_redelivery():
    """The consumer group is at-least-once (redis_bus.py), so the same
    transcription can arrive twice -- ON CONFLICT DO NOTHING on
    (raw_header, timestamp_ns) is what keeps it from showing up twice in
    the UI."""
    pool = FakePool()
    await db.insert_transcript(
        pool,
        {
            "raw_header": "ZCZC-WXR-TOR-041051+0030-2210300-KPTL/NWS-",
            "timestamp_ns": 1_700_000_000_000_000_000,
            "site": "home",
            "channel": "WX5",
            "event_code": "TOR",
            "tier": "A",
            "fips_codes": ["041051"],
            "text": "tornado warning",
            "passed_guard": True,
            "guard_reason": None,
            "wav_path": "/captures/a.wav",
        },
    )

    query, args = pool.executed[0]
    assert "ON CONFLICT (raw_header, timestamp_ns) DO NOTHING" in query
    assert args[0] == "ZCZC-WXR-TOR-041051+0030-2210300-KPTL/NWS-"
    assert args[6] == ["041051"]


async def test_insert_transcript_tolerates_a_payload_with_no_wav_path():
    """wav_path was added to GuardedTranscript after the fact; a transcript
    published by an older stt_worker still has to land."""
    pool = FakePool()
    await db.insert_transcript(
        pool,
        {
            "raw_header": "ZCZC",
            "timestamp_ns": 1,
            "site": "home",
            "channel": "WX5",
            "event_code": "TOR",
            "tier": "A",
            "fips_codes": [],
            "text": "",
            "passed_guard": False,
            "guard_reason": "repeated_ngram",
        },
    )

    _query, args = pool.executed[0]
    assert args[-1] is None


async def test_insert_dispatch_converts_the_iso_timestamp():
    """asyncpg needs a real datetime for a timestamptz param -- JSON has no
    datetime type and asyncpg does not parse strings implicitly."""
    pool = FakePool()
    await db.insert_dispatch(
        pool,
        {
            "stage": "1",
            "alert_id": "abc123",
            "event_code": "TOR",
            "tier": "A",
            "fips_codes": ["041051"],
            "raw_header": "ZCZC",
            "sent": True,
            "reason": "serial",
            "dispatched_at": "2026-08-08T21:00:00+00:00",
        },
    )

    _query, args = pool.executed[0]
    assert isinstance(args[0], datetime)
    assert args[1] == "1"
    assert args[2] == "abc123"


async def test_insert_dispatch_of_a_stage_2_record_has_no_alert_id():
    pool = FakePool()
    await db.insert_dispatch(
        pool,
        {
            "stage": "2",
            "site": "home",
            "channel": "WX5",
            "event_code": "TOR",
            "tier": "A",
            "fips_codes": [],
            "raw_header": "ZCZC",
            "sent": False,
            "reason": "skipped_circuit_open",
            "dispatched_at": "2026-08-08T21:00:00+00:00",
        },
    )

    _query, args = pool.executed[0]
    assert args[2] is None  # alert_id
    assert args[3] == "home"


async def test_list_transcripts_filters_by_raw_header():
    pool = FakePool(fetch_results=[[]])
    await db.list_transcripts(pool, raw_header="ZCZC")

    query, args = pool.fetch_calls[0]
    assert "WHERE raw_header = $1" in query
    assert args == ("ZCZC", 100)


async def test_list_dispatches_unfiltered_orders_newest_first():
    pool = FakePool(fetch_results=[[]])
    await db.list_dispatches(pool, limit=5)

    query, args = pool.fetch_calls[0]
    assert "ORDER BY dispatched_at DESC" in query
    assert args == (5,)


async def test_health_history_buckets_the_window_and_ors_dead():
    """dead is BOOL_OR'd, not averaged: a channel dead for part of a bucket
    has to render as dead, not as a fraction that rounds away."""
    pool = FakePool(fetch_results=[[]])
    await db.health_history(pool, since_seconds=3600, buckets=60)

    query, args = pool.fetch_calls[0]
    assert "time_bucket" in query
    assert "BOOL_OR(dead)" in query
    assert args == (3600.0, 60.0)


async def test_dispatch_summary_splits_sent_from_skipped():
    pool = FakePool(
        fetch_results=[
            [
                {"sent": True, "reason": "serial", "count": 2},
                {"sent": True, "reason": "mqtt_fallback", "count": 1},
                {"sent": False, "reason": "skipped_duplicate", "count": 4},
            ]
        ]
    )

    summary = await db.dispatch_summary(pool)

    assert summary["sent"] == 3
    assert summary["skipped"] == 4
    assert summary["by_reason"] == {"serial": 2, "mqtt_fallback": 1, "skipped_duplicate": 4}
