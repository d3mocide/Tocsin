import json

from sdr_rx.health import ChannelHealth
from sdr_rx.redis_sink import HEALTH_STREAM_NAME, RedisSpectrumSink, RedisStreamHealthSink, SPECTRUM_KEY_PREFIX
from sdr_rx.spectrum import SpectrumSnapshot


class FakeRedis:
    def __init__(self):
        self.xadd_calls = []
        self.set_calls = []

    def xadd(self, name, fields, maxlen=None, approximate=None):
        self.xadd_calls.append({"name": name, "fields": fields, "maxlen": maxlen, "approximate": approximate})

    def set(self, key, value):
        self.set_calls.append({"key": key, "value": value})


def test_health_sink_xadds_to_the_documented_stream():
    redis = FakeRedis()
    sink = RedisStreamHealthSink(redis)

    sink.record(ChannelHealth(site="home", channel="WX5", timestamp_ns=1, rms=0.1, power=0.01, dead=False))

    assert len(redis.xadd_calls) == 1
    call = redis.xadd_calls[0]
    assert call["name"] == HEALTH_STREAM_NAME
    payload = json.loads(call["fields"]["payload"])
    assert payload["site"] == "home"
    assert payload["channel"] == "WX5"
    assert payload["dead"] is False


def test_spectrum_sink_sets_a_per_site_key():
    redis = FakeRedis()
    sink = RedisSpectrumSink(redis)

    sink.record(
        SpectrumSnapshot(site="home", timestamp_ns=1, bin_frequencies_hz=(162_400_000.0,), bin_power_db=(-40.0,))
    )

    assert len(redis.set_calls) == 1
    call = redis.set_calls[0]
    assert call["key"] == f"{SPECTRUM_KEY_PREFIX}:home"
    payload = json.loads(call["value"])
    assert payload["site"] == "home"
    assert payload["bin_power_db"] == [-40.0]


def test_spectrum_sink_key_is_per_site():
    redis = FakeRedis()
    sink = RedisSpectrumSink(redis)
    sink.record(SpectrumSnapshot(site="home", timestamp_ns=1, bin_frequencies_hz=(), bin_power_db=()))
    sink.record(SpectrumSnapshot(site="office", timestamp_ns=1, bin_frequencies_hz=(), bin_power_db=()))
    keys = {call["key"] for call in redis.set_calls}
    assert keys == {f"{SPECTRUM_KEY_PREFIX}:home", f"{SPECTRUM_KEY_PREFIX}:office"}
