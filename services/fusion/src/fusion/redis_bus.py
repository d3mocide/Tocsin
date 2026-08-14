"""Consumes SAME events, CAP alerts, and keyword-matched transcript events
from Redis Streams via consumer groups (design doc §5: "Both paths write
raw events to Redis Streams before fusion sees them. If fusion crashes
mid-event it resumes from the consumer group rather than losing an
alert.").

Three independent streams, one shared group -- `tocsin:same_events`
(produced by `same_decoder.redis_sink`), `tocsin:cap_alerts` (produced by
`nws_poller.redis_sink`), and `tocsin:keyword_events` (produced by
`stt_worker.redis_sink`, the live-transcription addendum to §5). Not
shared imports from any producer -- service boundary (CLAUDE.md); the
stream names and JSON payload shapes below are the documented wire
contract each producer's own module points back to.

Consumer-group durability here is "at least once," not "exactly once": on
restart after a crash, `_replay_pending` re-delivers whatever entries this
consumer read but never XACKed, which can call `AlertStore.ingest_*` a
second time for an event already processed before the crash. The design
doc's own stated tradeoff ("resumes... rather than losing an alert")
accepts this -- a duplicate `Alert` is a much smaller problem than a
silently dropped one, and `same_decoder`'s TTL header dedup / `nws_poller`'s
`(id, sent)` tracking already keep steady-state redelivery rare in
practice. See `store.py`'s own docstring for what's explicitly not handled
yet.

Requires the redis client to be constructed with `decode_responses=True`
(see `__init__.py`) so stream/field values arrive as `str`, not `bytes` --
keeps this module free of encode/decode bookkeeping throughout.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .models import CapAlertIn, KeywordEventIn, SameEventIn
from .store import AlertStore

SAME_STREAM = "tocsin:same_events"
CAP_STREAM = "tocsin:cap_alerts"
KEYWORD_STREAM = "tocsin:keyword_events"
GROUP_NAME = "fusion"

_CAP_DATETIME_FIELDS = ("sent", "effective", "onset", "expires", "ends")


def _parse_keyword_payload(payload: dict) -> KeywordEventIn:
    return KeywordEventIn(
        site=payload["site"],
        channel=payload["channel"],
        received_at=datetime.fromtimestamp(payload["timestamp_ns"] / 1e9, tz=timezone.utc),
        event_code=payload["event_code"],
        event_name=payload["event_name"],
        tier=payload["tier"],
        matched_phrase=payload["matched_phrase"],
        transcript_text=payload["transcript_text"],
    )


def _parse_same_payload(payload: dict) -> SameEventIn:
    return SameEventIn(
        site=payload["site"],
        channel=payload["channel"],
        received_at=datetime.fromtimestamp(payload["timestamp_ns"] / 1e9, tz=timezone.utc),
        event_code=payload["event_code"],
        event_name=payload["event_name"],
        tier=payload["tier"],
        fips_codes=tuple(payload["fips_codes"]),
        originator=payload["originator"],
        callsign=payload["callsign"],
        purge_minutes=payload["purge_minutes"],
        raw_header=payload["raw_header"],
    )


def _parse_cap_payload(payload: dict) -> CapAlertIn:
    times = {
        field: (datetime.fromisoformat(payload[field]) if payload[field] else None)
        for field in _CAP_DATETIME_FIELDS
    }
    return CapAlertIn(
        id=payload["id"],
        event=payload["event"],
        headline=payload["headline"],
        status=payload["status"],
        message_type=payload["message_type"],
        category=payload["category"],
        severity=payload["severity"],
        certainty=payload["certainty"],
        urgency=payload["urgency"],
        area_desc=payload["area_desc"],
        same_codes=tuple(payload["same_codes"]),
        ugc_codes=tuple(payload["ugc_codes"]),
        vtec=payload["vtec"],
        **times,
    )


def ensure_group(redis_client, stream: str, group: str = GROUP_NAME) -> None:
    """Creates the consumer group starting from the beginning of the
    stream, with `MKSTREAM` so it also works against a stream that doesn't
    exist yet -- `nws-poller`/`same-decoder` might not have published
    anything when `fusion` first starts. `BUSYGROUP` means the group
    already exists, the expected steady-state case on every restart after
    the first."""
    try:
        redis_client.xgroup_create(stream, group, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


class StreamConsumer:
    def __init__(
        self,
        redis_client,
        store: AlertStore,
        consumer_name: str,
        group: str = GROUP_NAME,
        count: int = 100,
    ):
        self._redis = redis_client
        self._store = store
        self._consumer_name = consumer_name
        self._group = group
        self._count = count
        ensure_group(self._redis, SAME_STREAM, group)
        ensure_group(self._redis, CAP_STREAM, group)
        ensure_group(self._redis, KEYWORD_STREAM, group)
        self._replay_pending()

    def _replay_pending(self) -> None:
        """Reuses this consumer's own still-pending entries from a prior
        crash (Redis's `"0"` read-id, vs. `">"` for genuinely new entries)
        -- this is the actual resume-after-crash mechanism, not just an
        artifact of using consumer groups at all."""
        self._read_and_handle(SAME_STREAM, "0", self._handle_same, block_ms=None)
        self._read_and_handle(CAP_STREAM, "0", self._handle_cap, block_ms=None)
        self._read_and_handle(KEYWORD_STREAM, "0", self._handle_keyword, block_ms=None)

    def poll_once(self, block_ms: int = 1000) -> int:
        """Reads new entries (if any) from all three streams; returns the
        number processed. `block_ms` applies per stream, so worst-case
        latency for a full cycle is roughly `3 * block_ms` -- fine for
        this volume (alerts, not continuous telemetry)."""
        processed = self._read_and_handle(SAME_STREAM, ">", self._handle_same, block_ms=block_ms)
        processed += self._read_and_handle(CAP_STREAM, ">", self._handle_cap, block_ms=block_ms)
        processed += self._read_and_handle(KEYWORD_STREAM, ">", self._handle_keyword, block_ms=block_ms)
        return processed

    def _read_and_handle(self, stream: str, read_id: str, handler, block_ms: int | None) -> int:
        kwargs = {"count": self._count}
        if block_ms is not None:
            kwargs["block"] = block_ms
        response = self._redis.xreadgroup(self._group, self._consumer_name, {stream: read_id}, **kwargs)
        if not response:
            return 0
        processed = 0
        for _stream_name, entries in response:
            for entry_id, fields in entries:
                handler(json.loads(fields["payload"]))
                self._redis.xack(stream, self._group, entry_id)
                processed += 1
        return processed

    def _handle_same(self, payload: dict) -> None:
        self._store.ingest_same(_parse_same_payload(payload))

    def _handle_cap(self, payload: dict) -> None:
        self._store.ingest_cap(_parse_cap_payload(payload))

    def _handle_keyword(self, payload: dict) -> None:
        self._store.ingest_keyword(_parse_keyword_payload(payload))
