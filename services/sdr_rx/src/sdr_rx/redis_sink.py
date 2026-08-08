"""Publishes RF health samples and spectrum snapshots to Redis for
Phase 8's `api` service to consume.

Two different durability levels, deliberately: `RedisStreamHealthSink`
uses a Redis Stream (`tocsin:health`, XADD) -- health is a time series
worth keeping history for (design doc §3's flat-carrier detection is
exactly the kind of thing you want to look back at after the fact).
`RedisSpectrumSink` uses a plain key (SET, overwritten every publish) --
a waterfall display only ever wants "what does the spectrum look like
right now," not a log of every past snapshot, so paying for stream/
consumer-group bookkeeping here would be pure overhead (see
`spectrum.py`'s own docstring).
"""

from __future__ import annotations

import json
from dataclasses import asdict

from .health import ChannelHealth
from .spectrum import SpectrumSnapshot

HEALTH_STREAM_NAME = "tocsin:health"
DEFAULT_HEALTH_MAXLEN = 10_000
SPECTRUM_KEY_PREFIX = "tocsin:spectrum"


class RedisStreamHealthSink:
    def __init__(self, redis_client, stream_name: str = HEALTH_STREAM_NAME, maxlen: int = DEFAULT_HEALTH_MAXLEN):
        self._redis = redis_client
        self._stream_name = stream_name
        self._maxlen = maxlen

    def record(self, health: ChannelHealth) -> None:
        self._redis.xadd(
            self._stream_name,
            {"payload": json.dumps(asdict(health))},
            maxlen=self._maxlen,
            approximate=True,
        )


class RedisSpectrumSink:
    def __init__(self, redis_client, key_prefix: str = SPECTRUM_KEY_PREFIX):
        self._redis = redis_client
        self._key_prefix = key_prefix

    def record(self, snapshot: SpectrumSnapshot) -> None:
        key = f"{self._key_prefix}:{snapshot.site}"
        self._redis.set(key, json.dumps(asdict(snapshot)))
