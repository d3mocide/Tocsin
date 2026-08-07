"""live-audio entrypoint: subscribe to sdr-rx's `stt.*` topic, push each
(site, channel) as an Ogg/Vorbis stream to Icecast via ffmpeg.

Requires ffmpeg on PATH (installed via apt in the Dockerfile) and a
reachable Icecast server; neither is available in this authoring sandbox,
so this entrypoint itself isn't exercised end to end here -- the pieces
upstream of the real ffmpeg/Icecast (the ZMQ subscriber, the feeder
subprocess wrapper's plumbing, mount-name/URL building, per-channel
lazy-creation and dead-feeder handling) are unit tested instead.
"""

from __future__ import annotations

import os

from .service import IcecastConfig, Streamer
from .subscriber import StreamAudioSubscriber

DEFAULT_ZMQ_CONNECT = "tcp://sdr-rx:5555"
DEFAULT_ICECAST_HOST = "icecast"
DEFAULT_ICECAST_PORT = 8000
DEFAULT_ICECAST_USER = "source"


def main() -> None:
    connect_addr = os.environ.get("LIVE_AUDIO_ZMQ_CONNECT", DEFAULT_ZMQ_CONNECT)
    icecast = IcecastConfig(
        host=os.environ.get("ICECAST_HOST", DEFAULT_ICECAST_HOST),
        port=int(os.environ.get("ICECAST_PORT", DEFAULT_ICECAST_PORT)),
        user=os.environ.get("ICECAST_SOURCE_USER", DEFAULT_ICECAST_USER),
        password=os.environ.get("ICECAST_SOURCE_PASSWORD", "hackme"),
    )

    subscriber = StreamAudioSubscriber(connect_addr)
    streamer = Streamer(icecast)
    print(f"live-audio: subscribed to {connect_addr}, pushing to {icecast.host}:{icecast.port}", flush=True)
    try:
        while True:
            received = subscriber.recv(timeout_ms=1000)
            if received is None:
                continue
            site, channel, sample_rate_hz, pcm = received
            streamer.feed(site, channel, sample_rate_hz, pcm)
    except KeyboardInterrupt:
        pass
    finally:
        streamer.close()
        subscriber.close()
