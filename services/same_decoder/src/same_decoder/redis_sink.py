"""Publishes SAME events to Redis Streams so `fusion` can consume them
durably (design doc §5: "Both paths write raw events to Redis Streams
before fusion sees them" -- if fusion crashes mid-event it resumes from the
consumer group rather than losing an alert).

Not a shared import from `fusion` -- service boundary (CLAUDE.md). The
stream name and payload shape below are the documented wire contract;
`fusion`'s consumer duplicates this knowledge the same way
`same_decoder.subscriber` duplicates `sdr_rx.bus`'s ZMQ wire format.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from .service import EventSink, SameEvent

STREAM_NAME = "tocsin:same_events"
DEFAULT_MAXLEN = 10_000


class RedisStreamEventSink(EventSink):
    def __init__(self, redis_client, stream_name: str = STREAM_NAME, maxlen: int = DEFAULT_MAXLEN):
        self._redis = redis_client
        self._stream_name = stream_name
        self._maxlen = maxlen

    def record(self, event: SameEvent) -> None:
        self._redis.xadd(
            self._stream_name,
            {"payload": json.dumps(asdict(event))},
            maxlen=self._maxlen,
            approximate=True,
        )
