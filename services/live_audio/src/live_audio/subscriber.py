"""ZMQ SUB client for sdr-rx's `stt.<site>.<channel>` topic.

Deliberately not a shared import from `sdr_rx` -- see the identically-named
module in `same_decoder` for why (CLAUDE.md: services communicate over ZMQ,
not Python imports, across the service boundary).
"""

from __future__ import annotations

import json

import zmq

TOPIC_PREFIX = "stt."


class StreamAudioSubscriber:
    # Smaller default rcvhwm than same_decoder's subscriber: sdr_rx's
    # bus.py docstring calls out that dropping under load is *correct* for
    # live audio (better to skip samples than lag), the opposite of
    # same-decoder's generous-HWM requirement.
    def __init__(self, connect_addr: str, context: zmq.Context | None = None, rcvhwm: int = 10_000):
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
