import json
from datetime import datetime, timezone

from nws_poller.parser import CapAlert
from nws_poller.redis_sink import LoggingCapAlertSink, RedisStreamCapAlertSink, STREAM_NAME, serialize


def _alert():
    return CapAlert(
        id="a1",
        event="Tornado Warning",
        headline="Tornado Warning issued",
        status="Actual",
        message_type="Alert",
        category="Met",
        severity="Extreme",
        certainty="Observed",
        urgency="Immediate",
        area_desc="Multnomah, OR",
        sent=datetime(2026, 8, 8, 14, 0, tzinfo=timezone.utc),
        effective=None,
        onset=None,
        expires=None,
        ends=None,
        same_codes=("041051",),
        ugc_codes=("ORZ006",),
        vtec=None,
    )


class FakeRedis:
    def __init__(self):
        self.calls = []

    def xadd(self, name, fields, maxlen=None, approximate=None):
        self.calls.append({"name": name, "fields": fields, "maxlen": maxlen, "approximate": approximate})


def test_serialize_converts_datetimes_to_isoformat_and_stays_json_safe():
    data = serialize(_alert())
    json.dumps(data)  # must not raise
    assert data["sent"] == "2026-08-08T14:00:00+00:00"
    assert data["effective"] is None
    assert data["same_codes"] == ("041051",)


def test_redis_sink_xadds_to_the_documented_stream():
    redis = FakeRedis()
    sink = RedisStreamCapAlertSink(redis)

    sink.record(_alert())

    assert len(redis.calls) == 1
    call = redis.calls[0]
    assert call["name"] == STREAM_NAME
    payload = json.loads(call["fields"]["payload"])
    assert payload["id"] == "a1"
    assert payload["event"] == "Tornado Warning"


def test_logging_sink_prints_json(capsys):
    LoggingCapAlertSink().record(_alert())
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["id"] == "a1"
