from datetime import datetime, timezone

from nws_poller.parser import CapAlert
from nws_poller.tracker import SeenAlertTracker


def _alert(id="a1", sent="2026-08-08T14:00:00+00:00"):
    return CapAlert(
        id=id,
        event="Tornado Warning",
        headline=None,
        status="Actual",
        message_type="Alert",
        category="Met",
        severity="Extreme",
        certainty="Observed",
        urgency="Immediate",
        area_desc="",
        sent=datetime.fromisoformat(sent),
        effective=None,
        onset=None,
        expires=None,
        ends=None,
        same_codes=(),
        ugc_codes=(),
        vtec=None,
    )


def test_new_alert_is_emitted():
    tracker = SeenAlertTracker()
    fresh = tracker.filter_new_or_updated((_alert(),))
    assert len(fresh) == 1


def test_unchanged_alert_is_not_re_emitted():
    tracker = SeenAlertTracker()
    alert = _alert()
    tracker.filter_new_or_updated((alert,))
    fresh = tracker.filter_new_or_updated((alert,))
    assert fresh == []


def test_updated_alert_with_new_sent_is_re_emitted():
    tracker = SeenAlertTracker()
    tracker.filter_new_or_updated((_alert(sent="2026-08-08T14:00:00+00:00"),))
    fresh = tracker.filter_new_or_updated((_alert(sent="2026-08-08T14:10:00+00:00"),))
    assert len(fresh) == 1


def test_different_ids_both_emitted():
    tracker = SeenAlertTracker()
    fresh = tracker.filter_new_or_updated((_alert(id="a1"), _alert(id="a2")))
    assert {a.id for a in fresh} == {"a1", "a2"}
