"""ZMQ PUB publisher for finished captures (design doc §4 -> §6 handoff):
one JSON message per finalized WAV, naming its path on the shared
`segment-captures` volume plus the voice-start trim boundary `stt_worker`
needs (design doc §6's "trim before inference" step).

Mirrors `sdr_rx.bus.Publisher`'s shape (one PUB socket, topic per key) but
carries a JSON payload only -- no PCM frame, since the audio itself lives
on disk, not on the wire.

Two payload shapes share this one socket, discriminated by `capture_kind`:
`"alert"` (the original shape, `publish()`, SAME-triggered) and `"live"`
(`publish_live()`, `live_segmenter.LiveSegmenter`'s continuous chunks --
the live-transcription addendum to design doc §4/§6). `stt_worker`'s
subscriber branches on this field rather than needing a second topic/
socket -- a live chunk carries no event code, tier, or FIPS at all, since
nothing has been decoded or matched yet at capture time.
"""

from __future__ import annotations

import json

import zmq

from .live_segmenter import LiveCaptureResult
from .recorder import CaptureResult

TOPIC_PREFIX = "capture"


class CapturePublisher:
    def __init__(self, bind_addr: str, context: zmq.Context | None = None):
        self._ctx = context or zmq.Context.instance()
        self._socket = self._ctx.socket(zmq.PUB)
        self._socket.bind(bind_addr)

    @property
    def last_endpoint(self) -> str:
        return self._socket.get(zmq.LAST_ENDPOINT).decode()

    def close(self) -> None:
        self._socket.close(linger=0)

    def publish(self, result: CaptureResult) -> None:
        topic = f"{TOPIC_PREFIX}.{result.site}.{result.channel}"
        payload = {
            "capture_kind": "alert",
            "site": result.site,
            "channel": result.channel,
            "event_code": result.event_code,
            "tier": result.tier,
            "fips_codes": list(result.fips_codes),
            "raw_header": result.raw_header,
            "wav_path": str(result.wav_path),
            "voice_start_sample": result.voice_start_sample,
            "num_samples": result.num_samples,
            "timed_out": result.timed_out,
            "had_gap": result.had_gap,
        }
        self._socket.send_multipart([topic.encode(), json.dumps(payload).encode()])

    def publish_live(self, result: LiveCaptureResult) -> None:
        topic = f"{TOPIC_PREFIX}.{result.site}.{result.channel}"
        payload = {
            "capture_kind": "live",
            "site": result.site,
            "channel": result.channel,
            "wav_path": str(result.wav_path),
            "num_samples": result.num_samples,
        }
        self._socket.send_multipart([topic.encode(), json.dumps(payload).encode()])
