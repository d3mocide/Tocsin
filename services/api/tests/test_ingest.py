import asyncio

from api.ingest import Ingestor
from api.sse import Broadcaster

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
    broadcast = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert broadcast == alert


async def test_handle_health_inserts_but_does_not_broadcast():
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
    assert queue.empty()  # health samples aren't part of the alert SSE feed
