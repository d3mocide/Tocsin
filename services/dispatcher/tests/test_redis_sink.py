import json
from datetime import datetime, timezone

from dispatcher.models import RFAlertIn, TranscriptIn
from dispatcher.redis_sink import STREAM_NAME, RedisStreamDispatchLog
from dispatcher.service import DispatchOutcome


class FakeRedis:
    def __init__(self, fail=False):
        self.entries = []
        self.fail = fail

    def xadd(self, stream, fields, maxlen=None, approximate=None):
        if self.fail:
            raise ConnectionError("redis is gone")
        self.entries.append((stream, fields, maxlen, approximate))


def _rf_alert(**overrides):
    defaults = dict(
        alert_id="abc123",
        event_code="TOR",
        tier="A",
        fips_codes=("041051",),
        purge_minutes=30,
        received_at=datetime(2026, 8, 8, 21, 0, tzinfo=timezone.utc),
        raw_header="ZCZC-WXR-TOR-041051+0030-2210300-KPTL/NWS-",
    )
    defaults.update(overrides)
    return RFAlertIn(**defaults)


def _transcript(**overrides):
    defaults = dict(
        site="home",
        channel="WX5",
        event_code="TOR",
        tier="A",
        fips_codes=("041051",),
        raw_header="ZCZC-WXR-TOR-041051+0030-2210300-KPTL/NWS-",
        text="a tornado warning is in effect",
        passed_guard=True,
        guard_reason=None,
    )
    defaults.update(overrides)
    return TranscriptIn(**defaults)


def _payload(redis):
    return json.loads(redis.entries[0][1]["payload"])


def test_a_successful_stage_1_send_is_recorded():
    redis = FakeRedis()
    RedisStreamDispatchLog(redis).record(_rf_alert(), DispatchOutcome(sent=True, reason="serial"))

    stream, _fields, maxlen, approximate = redis.entries[0]
    assert stream == STREAM_NAME
    assert (maxlen, approximate) == (10_000, True)

    payload = _payload(redis)
    assert payload["stage"] == "1"
    assert payload["alert_id"] == "abc123"
    assert payload["sent"] is True
    assert payload["reason"] == "serial"
    assert payload["fips_codes"] == ["041051"]


def test_the_negative_outcomes_are_recorded_too():
    """These are the interesting half: an alert exists and nothing reached
    the mesh. Until this stream existed they were only a line on stdout."""
    for reason in (
        "skipped_not_tier_a",
        "skipped_duplicate",
        "skipped_rate_limited",
        "skipped_already_sent",
        "serial_no_ack",
    ):
        redis = FakeRedis()
        RedisStreamDispatchLog(redis).record(_rf_alert(), DispatchOutcome(sent=False, reason=reason))

        payload = _payload(redis)
        assert payload["sent"] is False
        assert payload["reason"] == reason


def test_a_stage_2_record_carries_site_and_channel_instead_of_an_alert_id():
    redis = FakeRedis()
    RedisStreamDispatchLog(redis).record(_transcript(), DispatchOutcome(sent=True, reason="mqtt_fallback"))

    payload = _payload(redis)
    assert payload["stage"] == "2"
    assert payload["site"] == "home"
    assert payload["channel"] == "WX5"
    assert "alert_id" not in payload
    assert payload["text"] == "a tornado warning is in effect"


def test_a_stage_1_record_has_no_transcript_fields():
    redis = FakeRedis()
    RedisStreamDispatchLog(redis).record(_rf_alert(), DispatchOutcome(sent=True, reason="serial"))

    payload = _payload(redis)
    for absent in ("site", "channel", "text", "passed_guard"):
        assert absent not in payload


def test_dispatched_at_is_iso_formatted_for_the_consumer():
    redis = FakeRedis()
    RedisStreamDispatchLog(redis).record(_rf_alert(), DispatchOutcome(sent=True, reason="serial"))

    # api's db.insert_dispatch calls datetime.fromisoformat on this.
    assert datetime.fromisoformat(_payload(redis)["dispatched_at"]).tzinfo is not None


def test_a_failed_log_write_does_not_raise():
    """record() runs *after* the send. Letting an audit-log failure
    propagate would turn a delivered message into a crashed poll cycle."""
    RedisStreamDispatchLog(FakeRedis(fail=True)).record(
        _rf_alert(), DispatchOutcome(sent=True, reason="serial")
    )  # must not raise
