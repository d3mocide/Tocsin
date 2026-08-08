"""JSON serialization for `Alert` -- shared by every `AlertSink`
implementation (`store.LoggingAlertSink`, `redis_sink.RedisStreamAlertSink`)
so the wire shape published to `tocsin:alerts` is defined in exactly one
place. `dispatcher` (Phase 6) duplicates this shape on its consuming side,
same service-boundary posture as every other producer/consumer pair in
this repo (CLAUDE.md).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from enum import Enum

from .models import Alert


class _AlertJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, Enum):
            return o.value
        return super().default(o)


def serialize_alert(alert: Alert) -> dict:
    return json.loads(json.dumps(asdict(alert), cls=_AlertJSONEncoder))


def alert_to_json(alert: Alert) -> str:
    return json.dumps(asdict(alert), cls=_AlertJSONEncoder)
