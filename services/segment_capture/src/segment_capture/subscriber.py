"""ZMQ SUB client for sdr-rx's `same.<site>.<channel>` topic.

Deliberately not a shared import from `sdr_rx` -- services communicate over
ZMQ, not Python imports, across the service boundary (see CLAUDE.md). This
duplicates the small amount of wire-format knowledge (topic prefix, header
JSON shape) that `sdr_rx.bus.Publisher` also knows, rather than reaching
into that package -- identical to `same_decoder.subscriber` for the same
reason; `segment_capture` needs this same 22050 Hz feed to run its own
ZCZC/EOM boundary detector (see `boundary.py`, `multimon.py`) independently
of `same_decoder`'s.
"""

from __future__ import annotations

import json

import zmq

TOPIC_PREFIX = "same."


class SameAudioSubscriber:
    def __init__(self, connect_addr: str, context: zmq.Context | None = None, rcvhwm: int = 100_000):
        self._ctx = context or zmq.Context.instance()
        self._socket = self._ctx.socket(zmq.SUB)
        self._socket.set(zmq.RCVHWM, rcvhwm)
        self._socket.connect(connect_addr)
        self._socket.setsockopt(zmq.SUBSCRIBE, TOPIC_PREFIX.encode())

    def close(self) -> None:
        self._socket.close(linger=0)

    def recv(self, timeout_ms: int | None = None) -> tuple[str, str, int, bytes] | None:
        """Returns (site, channel, sample_rate_hz, pcm_bytes), or None if
        `timeout_ms` elapses with nothing received."""
        if timeout_ms is not None and not self._socket.poll(timeout_ms):
            return None
        _topic, header_bytes, pcm = self._socket.recv_multipart()
        header = json.loads(header_bytes)
        return header["site"], header["channel"], header["sample_rate_hz"], pcm
