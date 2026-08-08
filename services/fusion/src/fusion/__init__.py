"""fusion entrypoint: consume SAME events and CAP alerts from Redis
Streams, correlate them, emit canonical Alerts (design doc §5, §10
milestone 5).

Runs in both `offgrid` and `hybrid` (`compose.yaml`) -- `offgrid` never
sees a CAP alert (`nws-poller` doesn't run there), so every Alert simply
stays `RF_ONLY`, which is by design (design doc §5: "In offgrid, [RF_ONLY]
is the only possible state").
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from .heartbeat import Heartbeat
from .mapping import EventMapping
from .redis_bus import StreamConsumer
from .redis_sink import RedisStreamAlertSink
from .store import AlertStore

DEFAULT_REDIS_URL = "redis://redis:6379/0"
DEFAULT_MODE = "offgrid"

# Fixed, not hostname-derived: Redis's per-consumer-group pending-entries
# list (the thing `StreamConsumer._replay_pending` reads back on startup)
# is keyed by this exact string. A hostname-based default would silently
# lose crash recovery across container *recreation* (as opposed to a
# same-container restart), since Docker assigns a new hostname each time
# -- fusion is architecturally a singleton anyway (one process owns the
# correlation state in memory, mirroring sdr-rx's "one process owns the
# dongle" pattern), so there's no multi-consumer scenario a fixed name
# would break.
DEFAULT_CONSUMER_NAME = "fusion"


def main() -> None:
    mode = os.environ.get("TOCSIN_MODE", DEFAULT_MODE)
    data_dir = os.environ.get("TOCSIN_DATA_DIR")
    redis_url = os.environ.get("FUSION_REDIS_URL", DEFAULT_REDIS_URL)
    consumer_name = os.environ.get("FUSION_CONSUMER_NAME", DEFAULT_CONSUMER_NAME)

    try:
        mapping = EventMapping.load(Path(data_dir) if data_dir else None)
    except OSError as exc:
        print(f"fusion: could not load event mapping: {exc}", file=sys.stderr)
        sys.exit(1)

    import redis as redis_lib

    redis_client = redis_lib.from_url(redis_url, decode_responses=True)
    # Always the Redis sink here, not LoggingAlertSink's fallback -- fusion
    # already hard-requires Redis to consume its own input streams, so
    # there's no "no Redis configured" case left to preserve stdout-only
    # behavior for (unlike same_decoder/nws_poller, where Redis is
    # optional). AlertStore's own default stays LoggingAlertSink, for
    # tests and any non-compose use.
    store = AlertStore(mapping, mode, sink=RedisStreamAlertSink(redis_client))
    consumer = StreamConsumer(redis_client, store, consumer_name)
    heartbeat = Heartbeat(redis_client)

    print(f"fusion: mode={mode}, consuming as {consumer_name!r} from {redis_url}", flush=True)
    while True:
        try:
            heartbeat.beat(mode=mode)
            consumer.poll_once()
        except Exception as exc:
            # A single bad poll cycle (Redis blip, malformed payload) must
            # not crash-loop the whole process -- same posture as
            # nws_poller's main loop.
            print(f"fusion: poll cycle failed: {exc}", file=sys.stderr)
            time.sleep(1.0)
