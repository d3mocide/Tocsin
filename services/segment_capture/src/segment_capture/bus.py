"""ZMQ PUB publisher for finished captures (design doc §4 -> §6 handoff):
one JSON message per finalized WAV, naming its path on the shared
`segment-captures` volume plus the voice-start trim boundary `stt_worker`
needs (design doc §6's "trim before inference" step).

Mirrors `sdr_rx.bus.Publisher`'s shape (one PUB socket, topic per key) but
carries a JSON payload only -- no PCM frame, since the audio itself lives
on disk, not on the wire.
"""

from __future__ import annotations

import json

import zmq

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
