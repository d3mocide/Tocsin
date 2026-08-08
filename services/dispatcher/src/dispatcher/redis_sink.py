"""Publishes every stage-1/stage-2 dispatch decision to Redis Streams
(`tocsin:dispatches`) so `api` can answer the one question the rest of the
system cannot: *did the alert actually go out?*

Every other stream in this repo carries something that was observed (a
SAME header, a CAP alert, a transcript). This one carries what Tocsin
itself *did* -- including the negatives, which are the interesting half:
`skipped_not_tier_a`, `skipped_duplicate`, `skipped_rate_limited`,
`skipped_already_sent`, and `egress_failed` are all cases where an alert
exists but nothing reached the mesh, and until now they existed only as a
line on stdout.

Implements `service.DispatchLog`, replacing `LoggingDispatchLog` when a
Redis client is configured -- the same optional-sink seam every other
service uses for its Redis publisher.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone

from .models import RFAlertIn
from .service import DispatchInput, DispatchLog, DispatchOutcome

STREAM_NAME = "tocsin:dispatches"
DEFAULT_MAXLEN = 10_000


def _serialize(item: DispatchInput, outcome: DispatchOutcome) -> dict:
    """Flattens the two possible input shapes (`RFAlertIn` for stage 1,
    `TranscriptIn` for stage 2) into one record. They share `event_code`,
    `tier`, `fips_codes`, and `raw_header`; everything else is
    stage-specific and left absent rather than null-filled, so a consumer
    can tell "stage 1, no site" from "stage 2, site unknown"."""
    record = {
        "stage": "1" if isinstance(item, RFAlertIn) else "2",
        "event_code": item.event_code,
        "tier": item.tier,
        "fips_codes": list(item.fips_codes),
        "raw_header": item.raw_header,
        "sent": outcome.sent,
        "reason": outcome.reason,
        "dispatched_at": datetime.now(timezone.utc).isoformat(),
    }
    extra = asdict(item)
    for key in ("alert_id", "site", "channel", "text", "passed_guard", "guard_reason"):
        if key in extra:
            record[key] = extra[key]
    return record


class RedisStreamDispatchLog(DispatchLog):
    def __init__(self, redis_client, stream_name: str = STREAM_NAME, maxlen: int = DEFAULT_MAXLEN):
        self._redis = redis_client
        self._stream_name = stream_name
        self._maxlen = maxlen

    def record(self, item: DispatchInput, outcome: DispatchOutcome) -> None:
        payload = _serialize(item, outcome)
        print(f"dispatcher: {item.event_code} {list(item.fips_codes)} -> {outcome.reason}", flush=True)
        try:
            self._redis.xadd(
                self._stream_name,
                {"payload": json.dumps(payload)},
                maxlen=self._maxlen,
                approximate=True,
            )
        except Exception as exc:
            # A failed audit-log write must never suppress a dispatch that
            # already happened -- `record()` runs after the send, and the
            # stdout line above is still the durable-enough fallback.
            print(f"dispatcher: dispatch-log write failed: {exc}", flush=True)
