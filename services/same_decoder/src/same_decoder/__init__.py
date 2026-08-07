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

from .service import Decoder
from .subscriber import SameAudioSubscriber
from .tiers import TierTable

DEFAULT_ZMQ_CONNECT = "tcp://sdr-rx:5555"


def main() -> None:
    connect_addr = os.environ.get("SAME_DECODER_ZMQ_CONNECT", DEFAULT_ZMQ_CONNECT)
    data_dir = os.environ.get("TOCSIN_DATA_DIR")

    try:
        tiers = TierTable.load(Path(data_dir) if data_dir else None)
    except OSError as exc:
        print(f"same-decoder: could not load event-code table: {exc}", file=sys.stderr)
        sys.exit(1)

    subscriber = SameAudioSubscriber(connect_addr)
    decoder = Decoder(tiers)
    print(f"same-decoder: subscribed to {connect_addr}", flush=True)
    try:
        while True:
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
