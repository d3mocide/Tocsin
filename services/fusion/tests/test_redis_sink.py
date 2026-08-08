import json

from fusion.redis_sink import RedisStreamAlertSink, STREAM_NAME
from fusion.serialize import alert_to_json, serialize_alert

from fixtures import MULTNOMAH, same_event
from fusion.confidence import compute_confidence
from fusion.models import Alert, AlertState, RFSource


def _alert():
    event = same_event(fips_codes=(MULTNOMAH,))
    return Alert(
        id="abc123",
        state=AlertState.RF_ONLY,
        confidence=compute_confidence(AlertState.RF_ONLY, "hybrid"),
        event_name=event.event_name,
        fips_codes=event.fips_codes,
        first_seen=event.received_at,
        last_updated=event.received_at,
        sources=(RFSource(event),),
    )


class FakeRedis:
    def __init__(self):
        self.calls = []

    def xadd(self, name, fields, maxlen=None, approximate=None):
        self.calls.append({"name": name, "fields": fields, "maxlen": maxlen, "approximate": approximate})


def test_serialize_alert_is_json_safe_and_keeps_provenance():
    data = serialize_alert(_alert())
    json.dumps(data)  # must not raise
    assert data["state"] == "RF_ONLY"
    assert data["sources"][0]["kind"] == "RF"
    assert data["sources"][0]["event"]["event_code"] == "TOR"
    assert isinstance(data["sources"][0]["event"]["received_at"], str)


def test_alert_to_json_round_trips_through_json_loads():
    text = alert_to_json(_alert())
    data = json.loads(text)
    assert data["id"] == "abc123"


def test_redis_sink_xadds_to_the_documented_stream():
    redis = FakeRedis()
    sink = RedisStreamAlertSink(redis)

    sink.record(_alert())

    assert len(redis.calls) == 1
    call = redis.calls[0]
    assert call["name"] == STREAM_NAME
    payload = json.loads(call["fields"]["payload"])
    assert payload["id"] == "abc123"
    assert payload["sources"][0]["kind"] == "RF"
