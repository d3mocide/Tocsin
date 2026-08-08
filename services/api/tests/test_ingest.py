import asyncio

from api.ingest import Ingestor
from api.sse import EVENT_ALERT, EVENT_DISPATCH, EVENT_HEALTH, EVENT_TRANSCRIPT, Broadcaster

from fake_pool import FakePool


async def test_handle_alert_upserts_and_broadcasts():
    pool = FakePool()
    broadcaster = Broadcaster()
    queue = broadcaster.subscribe()
    ingestor = Ingestor(pool, broadcaster)

    alert = {
        "id": "abc123",
        "state": "RF_ONLY",
        "confidence": 0.6,
        "event_name": "Tornado Warning",
        "fips_codes": ["041051"],
        "first_seen": "2026-08-08T21:00:00+00:00",
        "last_updated": "2026-08-08T21:00:00+00:00",
        "sources": [],
    }
    await ingestor.handle_alert(alert)

    assert len(pool.executed) == 1  # the upsert ran
    assert await asyncio.wait_for(queue.get(), timeout=1.0) == (EVENT_ALERT, alert)


async def test_handle_health_inserts_and_broadcasts():
    """Health is pushed as well as stored now -- a channel going dead is
    design doc §3's primary liveness signal for the whole SDR path, and it
    used to wait up to a 5s poll interval to reach the screen."""
    pool = FakePool()
    broadcaster = Broadcaster()
    queue = broadcaster.subscribe()
    ingestor = Ingestor(pool, broadcaster)

    health = {
        "site": "home",
        "channel": "WX5",
        "timestamp_ns": 1,
        "rms": 0.1,
        "power": 0.01,
        "dead": False,
    }
    await ingestor.handle_health(health)

    assert len(pool.executed) == 1  # the insert ran
    assert await asyncio.wait_for(queue.get(), timeout=1.0) == (EVENT_HEALTH, health)


async def test_handle_transcript_inserts_and_broadcasts():
    pool = FakePool()
    broadcaster = Broadcaster()
    queue = broadcaster.subscribe()
    ingestor = Ingestor(pool, broadcaster)

    transcript = {
        "site": "home",
        "channel": "WX5",
        "event_code": "TOR",
        "tier": "A",
        "fips_codes": ["041051"],
        "raw_header": "ZCZC-WXR-TOR-041051+0030-2210300-KPTL/NWS-",
        "text": "The National Weather Service has issued a tornado warning",
        "passed_guard": True,
        "guard_reason": None,
        "timestamp_ns": 1_700_000_000_000_000_000,
        "wav_path": "/var/lib/segment_capture/captures/home-WX5-1.wav",
    }
    await ingestor.handle_transcript(transcript)

    assert len(pool.executed) == 1
    assert await asyncio.wait_for(queue.get(), timeout=1.0) == (EVENT_TRANSCRIPT, transcript)


async def test_handle_dispatch_inserts_and_broadcasts():
    pool = FakePool()
    broadcaster = Broadcaster()
    queue = broadcaster.subscribe()
    ingestor = Ingestor(pool, broadcaster)

    dispatch = {
        "stage": "1",
        "alert_id": "abc123",
        "event_code": "TOR",
        "tier": "A",
        "fips_codes": ["041051"],
        "raw_header": "ZCZC-WXR-TOR-041051+0030-2210300-KPTL/NWS-",
        "sent": True,
        "reason": "serial",
        "dispatched_at": "2026-08-08T21:00:00+00:00",
    }
    await ingestor.handle_dispatch(dispatch)

    assert len(pool.executed) == 1
    assert await asyncio.wait_for(queue.get(), timeout=1.0) == (EVENT_DISPATCH, dispatch)
