"""ZMQ PUB publisher for channelizer output (design doc §3, "Output contract").

Multipart frames: `[topic][json header][pcm]`. One PUB socket serves every
channel and stream; consumers subscribe by topic prefix (`same.` for
multimon-ng-rate audio, `stt.` for STT/live-audio-rate audio, or a specific
`same.WX5` / `stt.WX5` for one channel).

PUB/SUB drops at the high-water mark once a subscriber's queue fills. That's
correct for `live-audio` (skipping samples under load beats lagging behind
live) and wrong for `same-decoder` (a dropped chunk during a SAME header is a
missed alert) -- per the design doc, give the decoder side a generous HWM.
Since HWM is enforced per-pipe from both the PUB and SUB ends, the default
here is deliberately large; `same-decoder` should still set its own
`rcvhwm` generously rather than relying on this default alone.
"""

from __future__ import annotations

import json
import time

import numpy as np
import zmq

DEFAULT_HWM = 100_000

TOPIC_SAME = "same"  # 22050 Hz s16le mono, for multimon-ng
TOPIC_STT = "stt"  # 16000 Hz s16le mono, for stt-worker / live-audio


class Publisher:
    """A single ZMQ PUB socket bound to `bind_addr`, shared across channels."""

    def __init__(self, bind_addr: str, context: zmq.Context | None = None, hwm: int = DEFAULT_HWM):
        self._ctx = context or zmq.Context.instance()
        self._socket = self._ctx.socket(zmq.PUB)
        self._socket.set_hwm(hwm)
        self._socket.bind(bind_addr)
        self._seq = 0

    @property
    def last_endpoint(self) -> str:
        return self._socket.get(zmq.LAST_ENDPOINT).decode()

    def close(self) -> None:
        self._socket.close(linger=0)

    def publish(self, topic: str, channel: str, sample_rate_hz: int, pcm: np.ndarray) -> None:
        """Send one chunk of s16le mono PCM for `channel` on `topic` (TOPIC_SAME/TOPIC_STT)."""
        pcm = np.ascontiguousarray(pcm, dtype=np.int16)
        header = {
            "channel": channel,
            "sample_rate_hz": sample_rate_hz,
            "dtype": "s16le",
            "num_samples": int(pcm.shape[0]),
            "seq": self._seq,
            "timestamp_ns": time.time_ns(),
        }
        self._seq += 1
        self._socket.send_multipart(
            [
                f"{topic}.{channel}".encode(),
                json.dumps(header).encode(),
                pcm.tobytes(),
            ]
        )
