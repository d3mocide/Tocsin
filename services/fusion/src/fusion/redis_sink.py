"""Publishes canonical Alerts to Redis Streams so `dispatcher` can consume
them durably -- the same "write raw events to Redis Streams" principle
design doc §5 states for `same_decoder`/`nws_poller`, extended one hop
downstream to fusion's own output. Not a shared import into `dispatcher`
-- service boundary (CLAUDE.md); `dispatcher`'s consumer duplicates this
stream name and payload shape the same way `fusion.redis_bus` duplicates
`same_decoder`/`nws_poller`'s.
"""

from __future__ import annotations

import json

from .models import Alert
from .serialize import serialize_alert

STREAM_NAME = "tocsin:alerts"
DEFAULT_MAXLEN = 10_000


class RedisStreamAlertSink:
    def __init__(self, redis_client, stream_name: str = STREAM_NAME, maxlen: int = DEFAULT_MAXLEN):
        self._redis = redis_client
        self._stream_name = stream_name
        self._maxlen = maxlen

    def record(self, alert: Alert) -> None:
        self._redis.xadd(
            self._stream_name,
            {"payload": json.dumps(serialize_alert(alert))},
            maxlen=self._maxlen,
            approximate=True,
        )
