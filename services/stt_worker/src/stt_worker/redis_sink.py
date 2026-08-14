"""Publishes guarded transcripts, and keyword-matched hazard events found
within them, to Redis Streams so downstream consumers see them durably --
same "write raw events to Redis Streams" principle design doc §5 states
for `same_decoder`/`nws_poller`, extended to `stt_worker`'s own output.
Not a shared import into `dispatcher`/`fusion` -- service boundary
(CLAUDE.md); each consumer duplicates the relevant stream name and payload
shape.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from .service import GuardedTranscript, KeywordEvent, KeywordEventSink, TranscriptSink

STREAM_NAME = "tocsin:transcripts"
KEYWORD_STREAM_NAME = "tocsin:keyword_events"
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


class RedisStreamKeywordEventSink(KeywordEventSink):
    """`fusion` consumes this stream the same way it consumes
    `tocsin:same_events` -- see its `redis_bus.py` -- to produce a
    `TRANSCRIPT_ONLY` alert (design doc's live-transcription addendum to
    §5)."""

    def __init__(self, redis_client, stream_name: str = KEYWORD_STREAM_NAME, maxlen: int = DEFAULT_MAXLEN):
        self._redis = redis_client
        self._stream_name = stream_name
        self._maxlen = maxlen

    def record(self, event: KeywordEvent) -> None:
        self._redis.xadd(
            self._stream_name,
            {"payload": json.dumps(asdict(event))},
            maxlen=self._maxlen,
            approximate=True,
        )
