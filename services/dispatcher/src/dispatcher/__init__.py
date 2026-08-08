"""dispatcher entrypoint: consume canonical Alerts from `tocsin:alerts`,
dispatch a stage-1 template message over Meshtastic serial for Tier A
alerts (design doc §7, §10 milestone 6).

Stage 1 only -- LLM enrichment (stage 2) and the Meshtastic MQTT
ack-fallback leg are Phase 7. Runs in both `offgrid` and `hybrid` (design
doc §2's architecture table lists `dispatcher` as "both") since stage 1 is
by definition network-independent.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from .dedup import AlertDeduplicator
from .fips import FipsTable
from .idempotency import IdempotencyStore
from .meshtastic_serial import MeshtasticSerialClient
from .models import parse_rf_source
from .rate_limit import TokenBucket
from .redis_bus import AlertStreamConsumer
from .service import Stage1Dispatcher

DEFAULT_REDIS_URL = "redis://redis:6379/0"

# Fixed, not hostname-derived -- see fusion/__init__.py's identical
# reasoning: Redis's per-consumer-group pending-entries list is keyed by
# this exact string, and dispatcher is a singleton the same way fusion is.
DEFAULT_CONSUMER_NAME = "dispatcher"


def main() -> None:
    data_dir = os.environ.get("TOCSIN_DATA_DIR")
    redis_url = os.environ.get("DISPATCHER_REDIS_URL", DEFAULT_REDIS_URL)
    consumer_name = os.environ.get("DISPATCHER_CONSUMER_NAME", DEFAULT_CONSUMER_NAME)
    # None -> meshtastic-python's SerialInterface autodetects the device;
    # set explicitly when more than one serial device is attached.
    serial_dev_path = os.environ.get("MESHTASTIC_SERIAL_DEV_PATH") or None

    try:
        fips_table = FipsTable.load(Path(data_dir) if data_dir else None)
    except OSError as exc:
        print(f"dispatcher: could not load FIPS table: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        mesh_client = MeshtasticSerialClient(dev_path=serial_dev_path)
    except Exception as exc:
        print(f"dispatcher: could not open Meshtastic serial interface: {exc}", file=sys.stderr)
        sys.exit(1)

    import redis as redis_lib

    redis_client = redis_lib.from_url(redis_url, decode_responses=True)
    dispatcher = Stage1Dispatcher(
        fips_table=fips_table,
        idempotency=IdempotencyStore(redis_client),
        dedup=AlertDeduplicator(),
        rate_limiter=TokenBucket(),
        mesh_client=mesh_client,
    )

    def handle_payload(payload: dict) -> None:
        rf_alert = parse_rf_source(payload)
        if rf_alert is not None:
            dispatcher.handle(rf_alert)

    consumer = AlertStreamConsumer(redis_client, handle_payload, consumer_name)
    print(f"dispatcher: consuming as {consumer_name!r} from {redis_url}", flush=True)
    while True:
        try:
            consumer.poll_once()
        except Exception as exc:
            # A single bad poll cycle (Redis blip, malformed payload) must
            # not crash-loop the whole process -- same posture as
            # fusion/nws_poller's main loops.
            print(f"dispatcher: poll cycle failed: {exc}", file=sys.stderr)
            time.sleep(1.0)
