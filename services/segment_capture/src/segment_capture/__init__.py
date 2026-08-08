"""segment-capture entrypoint: subscribe to sdr-rx's `same.*` topic, run an
independent ZCZC/EOM boundary detector per (site, channel), and capture
the full SAME message (header through EOM) from sdr-rx's shared ring
buffer into a WAV file plus voice-start metadata for stt_worker.

Requires multimon-ng on PATH (installed via apt in the Dockerfile) and a
reachable sdr-rx ZMQ PUB endpoint *and* its ring buffer directory mounted
at the same path sdr-rx writes to (the `sdr-rx-ring` shared volume in
compose.yaml) -- none of which is available in this authoring sandbox, so
this entrypoint itself isn't exercised end to end here. Every stage
upstream of the real multimon-ng binary and real ring-buffer files (line
parsing, the ring-buffer reader's pre-roll/live-drain/overrun logic, tone
boundary detection, the WAV writer, the capture-ready publisher, and the
service wiring) is unit tested instead.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .bus import CapturePublisher
from .service import SegmentCaptureService
from .subscriber import SameAudioSubscriber

DEFAULT_ZMQ_CONNECT = "tcp://sdr-rx:5555"
DEFAULT_ZMQ_BIND = "tcp://0.0.0.0:5556"
DEFAULT_RING_BUFFER_DIR = Path("/run/sdr_rx_ring")
DEFAULT_OUTPUT_DIR = Path("/var/lib/segment_capture/captures")
DEFAULT_PREROLL_SECONDS = 10.0
DEFAULT_HARD_TIMEOUT_SECONDS = 300.0


def main() -> None:
    connect_addr = os.environ.get("SEGMENT_CAPTURE_ZMQ_CONNECT", DEFAULT_ZMQ_CONNECT)
    bind_addr = os.environ.get("SEGMENT_CAPTURE_ZMQ_BIND", DEFAULT_ZMQ_BIND)
    ring_buffer_dir = Path(os.environ.get("SEGMENT_CAPTURE_RING_BUFFER_DIR", str(DEFAULT_RING_BUFFER_DIR)))
    output_dir = Path(os.environ.get("SEGMENT_CAPTURE_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)))
    preroll_seconds = float(os.environ.get("SEGMENT_CAPTURE_PREROLL_SECONDS", DEFAULT_PREROLL_SECONDS))
    hard_timeout_seconds = float(os.environ.get("SEGMENT_CAPTURE_HARD_TIMEOUT_SECONDS", DEFAULT_HARD_TIMEOUT_SECONDS))

    if not ring_buffer_dir.exists():
        print(
            f"segment-capture: ring buffer directory {ring_buffer_dir} does not exist -- "
            "is the sdr-rx-ring shared volume mounted? See services/segment_capture/README.md.",
            file=sys.stderr,
        )
        sys.exit(1)

    subscriber = SameAudioSubscriber(connect_addr)
    publisher = CapturePublisher(bind_addr)
    service = SegmentCaptureService(
        ring_buffer_dir=ring_buffer_dir,
        output_dir=output_dir,
        publisher=publisher,
        preroll_seconds=preroll_seconds,
        hard_timeout_seconds=hard_timeout_seconds,
    )
    print(f"segment-capture: subscribed to {connect_addr}, publishing captures on {bind_addr}", flush=True)
    try:
        while True:
            received = subscriber.recv(timeout_ms=1000)
            if received is not None:
                site, channel, _sample_rate_hz, pcm = received
                service.feed(site, channel, pcm)
            service.tick()
    except KeyboardInterrupt:
        pass
    finally:
        service.close()
        publisher.close()
        subscriber.close()
