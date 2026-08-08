"""Publishes CAP alerts to Redis Streams so `fusion` can consume them
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
from typing import Protocol

from .parser import CapAlert

STREAM_NAME = "tocsin:cap_alerts"
DEFAULT_MAXLEN = 10_000

_DATETIME_FIELDS = ("sent", "effective", "onset", "expires", "ends")


class CapAlertSink(Protocol):
    def record(self, alert: CapAlert) -> None: ...


class LoggingCapAlertSink:
    """Default sink: one JSON line per alert on stdout. Stands in for
    `RedisStreamCapAlertSink` when no `NWS_POLLER_REDIS_URL` is configured
    (local/test runs) -- same seam pattern as `same_decoder`'s
    `LoggingEventSink`."""

    def record(self, alert: CapAlert) -> None:
        print(json.dumps(serialize(alert)), flush=True)


class RedisStreamCapAlertSink:
    def __init__(self, redis_client, stream_name: str = STREAM_NAME, maxlen: int = DEFAULT_MAXLEN):
        self._redis = redis_client
        self._stream_name = stream_name
        self._maxlen = maxlen

    def record(self, alert: CapAlert) -> None:
        self._redis.xadd(
            self._stream_name,
            {"payload": json.dumps(serialize(alert))},
            maxlen=self._maxlen,
            approximate=True,
        )


def serialize(alert: CapAlert) -> dict:
    data = asdict(alert)
    for field in _DATETIME_FIELDS:
        if data[field] is not None:
            data[field] = data[field].isoformat()
    return data
