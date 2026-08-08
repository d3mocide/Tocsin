"""same-decoder entrypoint: subscribe to sdr-rx's `same.*` topic, decode SAME
headers via multimon-ng, log tiered events.

Requires multimon-ng on PATH (installed via apt in the Dockerfile) and a
reachable sdr-rx ZMQ PUB endpoint; neither is available in this authoring
sandbox, so this entrypoint itself isn't exercised end to end here -- every
stage upstream of the real multimon-ng binary (parser, tiers, dedup, the
subprocess wrapper's plumbing, the ZMQ subscriber) is unit tested instead.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import heartbeat as heartbeat_module
from .service import Decoder
from .subscriber import SameAudioSubscriber
from .tiers import TierTable

DEFAULT_ZMQ_CONNECT = "tcp://localhost:5555"


def _build_redis_client():
    """`None` when `SAME_DECODER_REDIS_URL` is unset. Built once in `main()`
    and shared by the event sink and the liveness heartbeat, rather than
    each opening its own connection to the same server."""
    redis_url = os.environ.get("SAME_DECODER_REDIS_URL")
    if not redis_url:
        return None
    import redis as redis_lib

    return redis_lib.from_url(redis_url)


def _build_sink(redis_client):
    """`None` falls back to `Decoder`'s own default (`LoggingEventSink`) --
    same seam pattern as `nws_poller._build_sink`. A real deployment sets
    `SAME_DECODER_REDIS_URL` (compose.yaml does) so `fusion` has something
    durable to read from (design doc §5); local/test runs without it still
    work, just logging to stdout instead."""
    if redis_client is None:
        return None
    from .redis_sink import RedisStreamEventSink

    return RedisStreamEventSink(redis_client)


def main() -> None:
    connect_addr = os.environ.get("SAME_DECODER_ZMQ_CONNECT", DEFAULT_ZMQ_CONNECT)
    data_dir = os.environ.get("TOCSIN_DATA_DIR")

    try:
        tiers = TierTable.load(Path(data_dir) if data_dir else None)
    except OSError as exc:
        print(f"same-decoder: could not load event-code table: {exc}", file=sys.stderr)
        sys.exit(1)

    redis_client = _build_redis_client()
    subscriber = SameAudioSubscriber(connect_addr)
    decoder = Decoder(tiers, sink=_build_sink(redis_client))
    heartbeat = heartbeat_module.build(redis_client)
    print(f"same-decoder: subscribed to {connect_addr}", flush=True)
    try:
        while True:
            if heartbeat is not None:
                heartbeat.beat()
            received = subscriber.recv(timeout_ms=1000)
            if received is None:
                continue
            site, channel, _sample_rate_hz, pcm = received
            decoder.feed(site, channel, pcm)
    except KeyboardInterrupt:
        pass
    finally:
        decoder.close()
        subscriber.close()
