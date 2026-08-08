"""ZMQ SUB client for segment_capture's `capture.<site>.<channel>` topic.

Deliberately duplicates the small amount of wire-format knowledge (topic
prefix, JSON payload shape) rather than importing across the service
boundary (CLAUDE.md) -- see `segment_capture.bus.CapturePublisher`, the
other end of this wire. Unlike `sdr_rx.bus.Publisher`'s frames, there's no
PCM part here: the audio lives on the shared `segment-captures` volume as
a WAV file, named in the payload, not on the wire.
"""

from __future__ import annotations

import json

import zmq

TOPIC_PREFIX = "capture."


class CaptureSubscriber:
    def __init__(self, connect_addr: str, context: zmq.Context | None = None, rcvhwm: int = 1000):
        self._ctx = context or zmq.Context.instance()
        self._socket = self._ctx.socket(zmq.SUB)
        self._socket.set(zmq.RCVHWM, rcvhwm)
        self._socket.connect(connect_addr)
        self._socket.setsockopt(zmq.SUBSCRIBE, TOPIC_PREFIX.encode())

    def close(self) -> None:
        self._socket.close(linger=0)

    def recv(self, timeout_ms: int | None = None) -> dict | None:
        if timeout_ms is not None and not self._socket.poll(timeout_ms):
            return None
        _topic, payload_bytes = self._socket.recv_multipart()
        return json.loads(payload_bytes)
