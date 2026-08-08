import json

from stt_worker.redis_sink import RedisStreamTranscriptSink, STREAM_NAME
from stt_worker.service import GuardedTranscript


class FakeRedis:
    def __init__(self):
        self.calls = []

    def xadd(self, name, fields, maxlen=None, approximate=None):
        self.calls.append({"name": name, "fields": fields, "maxlen": maxlen, "approximate": approximate})


def _transcript():
    return GuardedTranscript(
        site="home",
        channel="WX5",
        event_code="TOR",
        tier="A",
        fips_codes=("017021",),
        raw_header="ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-",
        text="a tornado warning",
        passed_guard=True,
        guard_reason=None,
        timestamp_ns=123,
    )


def test_xadds_to_the_documented_stream():
    redis = FakeRedis()
    sink = RedisStreamTranscriptSink(redis)

    sink.record(_transcript())

    assert len(redis.calls) == 1
    call = redis.calls[0]
    assert call["name"] == STREAM_NAME
    payload = json.loads(call["fields"]["payload"])
    assert payload["text"] == "a tornado warning"
    assert payload["raw_header"] == "ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-"
    assert payload["fips_codes"] == ["017021"]
