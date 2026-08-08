import json

from same_decoder.redis_sink import RedisStreamEventSink, STREAM_NAME
from same_decoder.service import SameEvent


class FakeRedis:
    def __init__(self):
        self.calls = []

    def xadd(self, name, fields, maxlen=None, approximate=None):
        self.calls.append({"name": name, "fields": fields, "maxlen": maxlen, "approximate": approximate})


def _event():
    return SameEvent(
        site="home",
        channel="WX5",
        timestamp_ns=123,
        event_code="TOR",
        event_name="Tornado Warning",
        tier="A",
        fips_codes=("017021",),
        originator="WXR",
        callsign="KILX/NWS",
        purge_minutes=45,
        raw_header="ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-",
    )


def test_xadds_to_the_documented_stream():
    redis = FakeRedis()
    sink = RedisStreamEventSink(redis)

    sink.record(_event())

    assert len(redis.calls) == 1
    call = redis.calls[0]
    assert call["name"] == STREAM_NAME
    payload = json.loads(call["fields"]["payload"])
    assert payload["event_code"] == "TOR"
    assert payload["fips_codes"] == ["017021"]
