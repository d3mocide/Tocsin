from datetime import timedelta

from fusion.models import AlertState, ApiSource, RFSource, TranscriptSource
from fusion.store import AlertStore

from fixtures import CLACKAMAS, MULTNOMAH, TOR_MAPPING, BASE_TIME, cap_alert, keyword_event, same_event


class FakeSink:
    def __init__(self):
        self.alerts = []

    def record(self, alert):
        self.alerts.append(alert)


def _store(mode="hybrid", sink=None):
    return AlertStore(TOR_MAPPING, mode, sink=sink or FakeSink())


def test_rf_only_when_no_cap_alert_seen():
    store = _store()
    alert = store.ingest_same(same_event())

    assert alert.state == AlertState.RF_ONLY
    assert len(alert.sources) == 1
    assert isinstance(alert.sources[0], RFSource)
    assert alert in store.open_alerts
    assert alert in store.all_alerts


def test_api_only_when_no_same_event_seen():
    store = _store()
    alert = store.ingest_cap(cap_alert())

    assert alert.state == AlertState.API_ONLY
    assert len(alert.sources) == 1
    assert isinstance(alert.sources[0], ApiSource)
    assert alert in store.open_alerts


def test_true_match_confirms_rf_then_cap():
    store = _store()
    rf_alert = store.ingest_same(same_event())
    assert rf_alert.state == AlertState.RF_ONLY

    confirmed = store.ingest_cap(cap_alert())

    assert confirmed.id == rf_alert.id
    assert confirmed.state == AlertState.CONFIRMED
    assert {type(s) for s in confirmed.sources} == {RFSource, ApiSource}
    assert confirmed not in store.open_alerts
    assert confirmed in store.all_alerts


def test_true_match_confirms_cap_then_rf():
    store = _store()
    api_alert = store.ingest_cap(cap_alert())
    assert api_alert.state == AlertState.API_ONLY

    confirmed = store.ingest_same(same_event())

    assert confirmed.id == api_alert.id
    assert confirmed.state == AlertState.CONFIRMED
    assert {type(s) for s in confirmed.sources} == {RFSource, ApiSource}


def test_near_miss_wrong_county_leaves_two_open_unconfirmed_alerts():
    store = _store()
    rf_alert = store.ingest_same(same_event(fips_codes=(MULTNOMAH,)))
    api_alert = store.ingest_cap(cap_alert(same_codes=(CLACKAMAS,)))

    assert rf_alert.state == AlertState.RF_ONLY
    assert api_alert.state == AlertState.API_ONLY
    assert rf_alert.id != api_alert.id
    assert len(store.open_alerts) == 2


def test_near_miss_wrong_event_leaves_two_open_unconfirmed_alerts():
    store = _store()
    rf_alert = store.ingest_same(same_event(event_code="TOR"))
    api_alert = store.ingest_cap(cap_alert(event="Severe Thunderstorm Warning"))

    assert rf_alert.state == AlertState.RF_ONLY
    assert api_alert.state == AlertState.API_ONLY
    assert len(store.open_alerts) == 2


def test_outside_time_tolerance_leaves_two_open_unconfirmed_alerts():
    store = _store()
    rf_alert = store.ingest_same(same_event(received_at=BASE_TIME))
    api_alert = store.ingest_cap(cap_alert(sent=BASE_TIME + timedelta(minutes=30)))

    assert rf_alert.state == AlertState.RF_ONLY
    assert api_alert.state == AlertState.API_ONLY


def test_confidence_is_mode_relative():
    offgrid_store = _store(mode="offgrid")
    hybrid_store = _store(mode="hybrid")

    offgrid_alert = offgrid_store.ingest_same(same_event())
    hybrid_alert = hybrid_store.ingest_same(same_event())

    assert offgrid_alert.confidence > hybrid_alert.confidence


def test_sink_receives_a_record_on_creation_and_on_confirmation():
    sink = FakeSink()
    store = _store(sink=sink)

    store.ingest_same(same_event())
    assert len(sink.alerts) == 1

    store.ingest_cap(cap_alert())
    assert len(sink.alerts) == 2
    assert sink.alerts[-1].state == AlertState.CONFIRMED


def test_repeated_cap_alert_updates_existing_alert_instead_of_duplicating():
    store = _store()
    cap1 = cap_alert(id="urn:oid:test.cap.1", sent=BASE_TIME)
    cap2 = cap_alert(id="urn:oid:test.cap.1", sent=BASE_TIME + timedelta(minutes=5))

    alert1 = store.ingest_cap(cap1)
    alert2 = store.ingest_cap(cap2)

    assert alert1.id == alert2.id
    assert len(store.all_alerts) == 1
    assert store.all_alerts[0].last_updated == BASE_TIME + timedelta(minutes=5)


def test_keyword_event_creates_transcript_only_alert():
    store = _store()
    alert = store.ingest_keyword(keyword_event())

    assert alert.state == AlertState.TRANSCRIPT_ONLY
    assert len(alert.sources) == 1
    assert isinstance(alert.sources[0], TranscriptSource)
    assert alert.fips_codes == ()
    assert alert in store.all_alerts


def test_transcript_only_alert_is_not_eligible_for_confirmation():
    """Unlike RF_ONLY/API_ONLY, a keyword-matched alert never enters
    `open_alerts` -- it's never attempted against the other source (see
    `store.ingest_keyword`'s docstring for why: no FIPS to correlate on)."""
    store = _store()
    alert = store.ingest_keyword(keyword_event())
    assert alert not in store.open_alerts

    # A CAP alert for the exact same event/area does not confirm it.
    confirmed_candidate = store.ingest_cap(cap_alert())
    assert confirmed_candidate.state == AlertState.API_ONLY
    assert alert.state == AlertState.TRANSCRIPT_ONLY


def test_repeated_keyword_event_on_same_channel_updates_existing_alert():
    store = _store()
    first = store.ingest_keyword(keyword_event(received_at=BASE_TIME))
    second = store.ingest_keyword(keyword_event(received_at=BASE_TIME + timedelta(seconds=30)))

    assert first.id == second.id
    assert len(store.all_alerts) == 1
    assert store.all_alerts[0].last_updated == BASE_TIME + timedelta(seconds=30)


def test_keyword_event_on_a_different_channel_creates_a_separate_alert():
    store = _store()
    first = store.ingest_keyword(keyword_event(channel="WX5"))
    second = store.ingest_keyword(keyword_event(channel="WX7"))

    assert first.id != second.id
    assert len(store.all_alerts) == 2


def test_keyword_event_confidence_is_mode_relative_and_below_rf_only():
    offgrid_store = _store(mode="offgrid")
    hybrid_store = _store(mode="hybrid")

    offgrid_alert = offgrid_store.ingest_keyword(keyword_event())
    hybrid_alert = hybrid_store.ingest_keyword(keyword_event())
    rf_alert = offgrid_store.ingest_same(same_event())

    assert offgrid_alert.confidence > hybrid_alert.confidence
    assert offgrid_alert.confidence < rf_alert.confidence
