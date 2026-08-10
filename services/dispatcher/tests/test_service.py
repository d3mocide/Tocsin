from datetime import datetime, timezone

from dispatcher.dedup import AlertDeduplicator
from dispatcher.egress.dispatch import EgressResult
from dispatcher.fips import FipsEntry, FipsTable
from dispatcher.idempotency import IdempotencyStore
from dispatcher.models import RFAlertIn
from dispatcher.rate_limit import TokenBucket
from dispatcher.service import Stage1Dispatcher

FIPS_TABLE = FipsTable({"41051": FipsEntry(county="Multnomah", state="OR")})


class FakeRedis:
    def __init__(self):
        self.store = {}

    def set(self, key, value, nx=None, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True


class FakeEgress:
    def __init__(self, result=None, raises=None):
        self.result = result or EgressResult(delivered=True, path="serial")
        self.raises = raises
        self.sent = []

    def send(self, text):
        self.sent.append(text)
        if self.raises:
            raise self.raises
        return self.result


class RecordingLog:
    def __init__(self):
        self.records = []

    def record(self, alert, outcome):
        self.records.append((alert, outcome))


def _rf_alert(
    event_code="TOR",
    tier="A",
    fips_codes=("041051",),
    raw_header="ZCZC-WXR-TOR-041051+0045-2202132-KPQR/NWS-",
    alert_id="a1",
):
    return RFAlertIn(
        alert_id=alert_id,
        event_code=event_code,
        tier=tier,
        fips_codes=fips_codes,
        purge_minutes=45,
        received_at=datetime(2026, 8, 8, 21, 0, tzinfo=timezone.utc),
        raw_header=raw_header,
    )


def _dispatcher(egress=None, redis=None, log=None):
    return Stage1Dispatcher(
        fips_table=FIPS_TABLE,
        idempotency=IdempotencyStore(redis or FakeRedis()),
        dedup=AlertDeduplicator(),
        rate_limiter=TokenBucket(),
        egress=egress or FakeEgress(),
        log=log,
    )


def test_tier_a_alert_is_sent():
    egress = FakeEgress()
    outcome = _dispatcher(egress=egress).handle(_rf_alert(tier="A"))

    assert outcome.sent is True
    assert outcome.reason == "serial"
    assert egress.sent == ["TOR WARN | Multnomah OR | exp 2145Z | RF"]


def test_tier_b_alert_never_reaches_the_mesh():
    egress = FakeEgress()
    outcome = _dispatcher(egress=egress).handle(_rf_alert(tier="B"))

    assert outcome.sent is False
    assert outcome.reason == "skipped_not_tier_a"
    assert egress.sent == []


def test_tier_c_alert_never_reaches_the_mesh():
    egress = FakeEgress()
    outcome = _dispatcher(egress=egress).handle(_rf_alert(tier="C"))

    assert outcome.reason == "skipped_not_tier_a"
    assert egress.sent == []


def test_no_ack_result_is_passed_through_from_egress():
    egress = FakeEgress(result=EgressResult(delivered=False, path="serial_no_ack"))
    outcome = _dispatcher(egress=egress).handle(_rf_alert())

    assert outcome.sent is False
    assert outcome.reason == "serial_no_ack"


def test_send_exception_does_not_propagate_and_idempotency_is_still_claimed():
    redis = FakeRedis()
    egress = FakeEgress(raises=RuntimeError("serial port gone"))
    dispatcher = _dispatcher(egress=egress, redis=redis)

    outcome = dispatcher.handle(_rf_alert())
    assert outcome.reason == "send_error"

    # the exact same header must not be retried -- see service.py's
    # docstring on why idempotency is claimed before the send is attempted
    egress2 = FakeEgress()
    outcome2 = _dispatcher(egress=egress2, redis=redis).handle(_rf_alert())
    assert outcome2.reason == "skipped_already_sent"
    assert egress2.sent == []


def test_a_second_identical_header_is_not_resent_even_across_a_new_dispatcher_instance():
    redis = FakeRedis()
    egress1 = FakeEgress()
    _dispatcher(egress=egress1, redis=redis).handle(_rf_alert())
    assert len(egress1.sent) == 1

    # simulates a dispatcher restart: fresh in-process state, same Redis
    egress2 = FakeEgress()
    outcome = _dispatcher(egress=egress2, redis=redis).handle(_rf_alert())

    assert outcome.reason == "skipped_already_sent"
    assert egress2.sent == []


def test_near_duplicate_alert_is_deduped_before_using_a_rate_limit_token():
    egress = FakeEgress()
    dispatcher = _dispatcher(egress=egress)
    dispatcher.handle(_rf_alert(raw_header="header-1"))
    outcome = dispatcher.handle(_rf_alert(raw_header="header-2"))  # same event+fips, different header

    assert outcome.reason == "skipped_duplicate"
    assert len(egress.sent) == 1


def test_rate_limit_blocks_the_fourth_alert_in_a_burst():
    egress = FakeEgress()
    dispatcher = _dispatcher(egress=egress)
    outcomes = [
        dispatcher.handle(_rf_alert(fips_codes=(f"04105{i}",), raw_header=f"header-{i}"))
        for i in range(4)
    ]

    assert [o.reason for o in outcomes[:3]] == ["serial", "serial", "serial"]
    assert outcomes[3].reason == "skipped_rate_limited"


def test_log_receives_every_outcome():
    log = RecordingLog()
    _dispatcher(log=log).handle(_rf_alert(tier="B"))
    assert len(log.records) == 1
    assert log.records[0][1].reason == "skipped_not_tier_a"
