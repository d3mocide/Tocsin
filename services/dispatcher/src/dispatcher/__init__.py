"""dispatcher entrypoint: consume canonical Alerts from `tocsin:alerts`
(stage 1, design doc §7 / roadmap.md Phase 6) and, when LiteLLM is
configured, guarded transcripts from `tocsin:transcripts` (stage 2,
Phase 7), dispatching over Meshtastic (serial primary, MQTT fallback in
hybrid mode).

Runs in both `offgrid` and `hybrid` (design doc §2's architecture table
lists `dispatcher` as "both") -- stage 1 itself is network-independent by
design; only the MQTT fallback leg (`egress/dispatch.py`) and stage 2's
LiteLLM call are mode/config-gated. Per design doc §8 ("In offgrid mode,
stage 2 is template-only or omitted entirely"), this takes the "omitted
entirely" option: without `DISPATCHER_LITELLM_BASE_URL` set, stage 2 is
skipped and `tocsin:transcripts` is never even consumed -- not a partial
template-only stage 2, which the design doc allows but doesn't require.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from .circuit_breaker import CircuitBreaker, DEFAULT_COOLDOWN_SECONDS, DEFAULT_FAILURE_THRESHOLD
from .dedup import AlertDeduplicator
from .egress.dispatch import DualPathSender
from .egress.meshtastic_mqtt import DEFAULT_REGION, MeshtasticMqttClient
from .egress.meshtastic_serial import MeshtasticSerialClient
from .fips import FipsTable
from .heartbeat import Heartbeat
from .idempotency import IdempotencyStore
from .litellm_client import DEFAULT_MODEL, LiteLLMClient
from .models import parse_rf_source, parse_transcript
from .rate_limit import TokenBucket
from .redis_bus import AlertStreamConsumer, TRANSCRIPTS_STREAM_NAME
from .redis_sink import RedisStreamDispatchLog
from .service import Stage1Dispatcher, Stage2Dispatcher

DEFAULT_REDIS_URL = "redis://redis:6379/0"
DEFAULT_MODE = "offgrid"
DEFAULT_MQTT_HOST = "mosquitto"
DEFAULT_MQTT_PORT = 1883

# Fixed, not hostname-derived -- see fusion/__init__.py's identical
# reasoning: Redis's per-consumer-group pending-entries list is keyed by
# this exact string, and dispatcher is a singleton the same way fusion is.
DEFAULT_CONSUMER_NAME = "dispatcher"

_FALSEY = {"false", "0", "no", "off"}


def _build_mqtt_client() -> MeshtasticMqttClient | None:
    """`None` when no gateway node is configured -- there's nothing to
    publish to. Safe to build even in `offgrid` mode: unlike
    `MeshtasticSerialClient`, this doesn't open any connection at
    construction time (see its own docstring), and `DualPathSender`'s
    `mode` check is what actually decides whether it's ever used."""
    gateway_node_id = os.environ.get("MESHTASTIC_GATEWAY_NODE_ID")
    if not gateway_node_id:
        return None
    return MeshtasticMqttClient(
        host=os.environ.get("MQTT_HOST", DEFAULT_MQTT_HOST),
        port=int(os.environ.get("MQTT_PORT", DEFAULT_MQTT_PORT)),
        gateway_node_id=int(gateway_node_id),
        region=os.environ.get("MESHTASTIC_MQTT_REGION", DEFAULT_REGION),
    )


def _mesh_enabled() -> bool:
    return os.environ.get("MESHTASTIC_ENABLED", "true").strip().lower() not in _FALSEY


def _build_serial_client() -> MeshtasticSerialClient | None:
    """`None` when `MESHTASTIC_ENABLED` is false -- running with no
    Meshtastic node attached at all is supported (see
    `egress/dispatch.py`), so this is the one path where failing to open
    the serial interface is deliberate rather than fatal.

    With mesh enabled, a node that won't open is still fatal (exit 1 under
    `restart: on-failure`): someone who configured a radio and lost it
    wants to know immediately, not to discover a silently muted station
    mid-event."""
    if not _mesh_enabled():
        print("dispatcher: MESHTASTIC_ENABLED=false -- mesh transmit disabled", flush=True)
        return None
    # None -> meshtastic-python's SerialInterface autodetects the device;
    # set explicitly when more than one serial device is attached.
    dev_path = os.environ.get("MESHTASTIC_SERIAL_DEV_PATH") or None
    try:
        return MeshtasticSerialClient(dev_path=dev_path)
    except Exception as exc:
        print(
            f"dispatcher: could not open Meshtastic serial interface: {exc}\n"
            "If no node is attached, set MESHTASTIC_ENABLED=false (and drop "
            "compose.mesh.yaml from COMPOSE_FILE) to run without one -- see "
            "services/dispatcher/README.md.",
            file=sys.stderr,
        )
        sys.exit(1)


def _build_stage2_dispatcher(redis_client, egress: DualPathSender, log) -> Stage2Dispatcher | None:
    base_url = os.environ.get("DISPATCHER_LITELLM_BASE_URL")
    if not base_url:
        return None
    litellm_client = LiteLLMClient(
        base_url=base_url,
        api_key=os.environ.get("DISPATCHER_LITELLM_API_KEY") or None,
        model=os.environ.get("DISPATCHER_LITELLM_MODEL", DEFAULT_MODEL),
    )
    circuit_breaker = CircuitBreaker(
        redis_client,
        failure_threshold=int(
            os.environ.get("DISPATCHER_CIRCUIT_BREAKER_THRESHOLD", DEFAULT_FAILURE_THRESHOLD)
        ),
        cooldown_seconds=int(
            os.environ.get("DISPATCHER_CIRCUIT_BREAKER_COOLDOWN_SECONDS", DEFAULT_COOLDOWN_SECONDS)
        ),
    )
    return Stage2Dispatcher(
        idempotency=IdempotencyStore(redis_client),
        circuit_breaker=circuit_breaker,
        litellm_client=litellm_client,
        egress=egress,
        log=log,
    )


def main() -> None:
    mode = os.environ.get("TOCSIN_MODE", DEFAULT_MODE)
    data_dir = os.environ.get("TOCSIN_DATA_DIR")
    redis_url = os.environ.get("DISPATCHER_REDIS_URL", DEFAULT_REDIS_URL)
    consumer_name = os.environ.get("DISPATCHER_CONSUMER_NAME", DEFAULT_CONSUMER_NAME)

    try:
        fips_table = FipsTable.load(Path(data_dir) if data_dir else None)
    except OSError as exc:
        print(f"dispatcher: could not load FIPS table: {exc}", file=sys.stderr)
        sys.exit(1)

    serial_client = _build_serial_client()
    egress = DualPathSender(serial_client=serial_client, mqtt_client=_build_mqtt_client(), mode=mode)

    import redis as redis_lib

    redis_client = redis_lib.from_url(redis_url, decode_responses=True)
    # Both stages share one log, so `api`'s /dispatches is a single
    # ordered record of everything dispatcher decided, not two feeds to
    # interleave client-side.
    dispatch_log = RedisStreamDispatchLog(redis_client)
    stage1 = Stage1Dispatcher(
        fips_table=fips_table,
        idempotency=IdempotencyStore(redis_client),
        dedup=AlertDeduplicator(),
        rate_limiter=TokenBucket(),
        egress=egress,
        log=dispatch_log,
    )
    stage2 = _build_stage2_dispatcher(redis_client, egress, dispatch_log)

    def handle_alert(payload: dict) -> None:
        rf_alert = parse_rf_source(payload)
        if rf_alert is not None:
            stage1.handle(rf_alert)

    consumers = [AlertStreamConsumer(redis_client, handle_alert, consumer_name)]
    if stage2 is not None:

        def handle_transcript(payload: dict) -> None:
            stage2.handle(parse_transcript(payload))

        consumers.append(
            AlertStreamConsumer(redis_client, handle_transcript, consumer_name, stream=TRANSCRIPTS_STREAM_NAME)
        )
        print("dispatcher: stage 2 enabled", flush=True)
    else:
        print("dispatcher: DISPATCHER_LITELLM_BASE_URL not set -- stage 2 disabled", flush=True)

    heartbeat = Heartbeat(redis_client)
    print(f"dispatcher: consuming as {consumer_name!r} from {redis_url}", flush=True)
    while True:
        try:
            # `mesh` rides along so the status board can distinguish "no
            # alerts tonight" from "transmit is off" -- otherwise a
            # deliberately mesh-less station looks identical to a broken one.
            heartbeat.beat(mode=mode, stage2=stage2 is not None, mesh=serial_client is not None)
            for consumer in consumers:
                consumer.poll_once()
        except Exception as exc:
            # A single bad poll cycle (Redis blip, malformed payload) must
            # not crash-loop the whole process -- same posture as
            # fusion/nws_poller's main loops.
            print(f"dispatcher: poll cycle failed: {exc}", file=sys.stderr)
            time.sleep(1.0)
