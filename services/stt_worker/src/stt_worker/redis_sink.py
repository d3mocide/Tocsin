"""Publishes guarded transcripts to Redis Streams so `dispatcher`'s stage
2 (Phase 7) can consume them durably -- same "write raw events to Redis
Streams" principle design doc §5 states for `same_decoder`/`nws_poller`,
extended to `stt_worker`'s own output. Not a shared import into
`dispatcher` -- service boundary (CLAUDE.md); `dispatcher`'s consumer
duplicates this stream name and payload shape.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from .service import GuardedTranscript, TranscriptSink

STREAM_NAME = "tocsin:transcripts"
DEFAULT_MAXLEN = 10_000


class RedisStreamTranscriptSink(TranscriptSink):
    def __init__(self, redis_client, stream_name: str = STREAM_NAME, maxlen: int = DEFAULT_MAXLEN):
        self._redis = redis_client
        self._stream_name = stream_name
        self._maxlen = maxlen

    def record(self, transcript: GuardedTranscript) -> None:
        self._redis.xadd(
            self._stream_name,
            {"payload": json.dumps(asdict(transcript))},
            maxlen=self._maxlen,
            approximate=True,
        )
