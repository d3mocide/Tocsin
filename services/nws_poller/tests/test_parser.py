from datetime import datetime, timezone

from nws_poller.parser import parse_feature


def _feature(**overrides):
    props = {
        "id": "urn:oid:2.49.0.1.840.0.example",
        "event": "Tornado Warning",
        "headline": "Tornado Warning issued",
        "status": "Actual",
        "messageType": "Alert",
        "category": "Met",
        "severity": "Extreme",
        "certainty": "Observed",
        "urgency": "Immediate",
        "areaDesc": "Multnomah, OR; Clackamas, OR",
        "sent": "2026-08-08T14:32:00-07:00",
        "effective": "2026-08-08T14:32:00-07:00",
        "onset": "2026-08-08T14:32:00-07:00",
        "expires": "2026-08-08T15:15:00-07:00",
        "ends": "2026-08-08T15:15:00-07:00",
        "geocode": {"SAME": ["041051", "041005"], "UGC": ["ORZ006", "ORZ007"]},
        "parameters": {"VTEC": ["/O.NEW.KPQR.TO.W.0012.260808T2132Z-260808T2215Z/"]},
    }
    props.update(overrides)
    return {"type": "Feature", "properties": props}


def test_parses_full_feature():
    alert = parse_feature(_feature())

    assert alert.id == "urn:oid:2.49.0.1.840.0.example"
    assert alert.event == "Tornado Warning"
    assert alert.status == "Actual"
    assert alert.message_type == "Alert"
    assert alert.same_codes == ("041051", "041005")
    assert alert.ugc_codes == ("ORZ006", "ORZ007")
    assert alert.vtec == "/O.NEW.KPQR.TO.W.0012.260808T2132Z-260808T2215Z/"
    assert alert.sent == datetime(2026, 8, 8, 14, 32, tzinfo=alert.sent.tzinfo)
    assert alert.sent.utcoffset().total_seconds() == -7 * 3600


def test_parses_missing_optional_fields_as_none_or_empty():
    props = _feature()
    props["properties"].pop("headline")
    props["properties"].pop("onset")
    props["properties"].pop("ends")
    props["properties"]["geocode"] = {}
    props["properties"]["parameters"] = {}

    alert = parse_feature(props)

    assert alert.headline is None
    assert alert.onset is None
    assert alert.ends is None
    assert alert.same_codes == ()
    assert alert.ugc_codes == ()
    assert alert.vtec is None


def test_zulu_timestamp_parses():
    alert = parse_feature(_feature(sent="2026-08-08T21:32:00Z"))
    assert alert.sent.tzinfo == timezone.utc
