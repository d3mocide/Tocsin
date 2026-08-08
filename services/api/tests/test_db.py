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
