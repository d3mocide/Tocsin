from dispatcher.models import parse_rf_source


def _same_event(**overrides):
    event = {
        "site": "home",
        "channel": "WX5",
        "received_at": "2026-08-08T21:00:00+00:00",
        "event_code": "TOR",
        "event_name": "Tornado Warning",
        "tier": "A",
        "fips_codes": ["041051"],
        "originator": "WXR",
        "callsign": "KPQR/NWS",
        "purge_minutes": 45,
        "raw_header": "ZCZC-WXR-TOR-041051+0045-2202132-KPQR/NWS-",
    }
    event.update(overrides)
    return event


def _cap_alert(**overrides):
    alert = {
        "id": "urn:oid:2.49.0.1.840.0.example",
        "event": "Tornado Warning",
        "same_codes": ["041051"],
    }
    alert.update(overrides)
    return alert


def test_rf_only_payload_parses():
    payload = {
        "id": "abc123",
        "state": "RF_ONLY",
        "sources": [{"event": _same_event(), "kind": "RF"}],
    }
    rf = parse_rf_source(payload)
    assert rf is not None
    assert rf.alert_id == "abc123"
    assert rf.event_code == "TOR"
    assert rf.tier == "A"
    assert rf.fips_codes == ("041051",)
    assert rf.purge_minutes == 45
    assert rf.raw_header == "ZCZC-WXR-TOR-041051+0045-2202132-KPQR/NWS-"


def test_api_only_payload_has_no_rf_source():
    payload = {
        "id": "abc123",
        "state": "API_ONLY",
        "sources": [{"alert": _cap_alert(), "kind": "API"}],
    }
    assert parse_rf_source(payload) is None


def test_confirmed_payload_finds_the_rf_source_among_both():
    payload = {
        "id": "abc123",
        "state": "CONFIRMED",
        "sources": [
            {"event": _same_event(), "kind": "RF"},
            {"alert": _cap_alert(), "kind": "API"},
        ],
    }
    rf = parse_rf_source(payload)
    assert rf is not None
    assert rf.event_code == "TOR"


def _keyword_event(**overrides):
    event = {
        "site": "home",
        "channel": "WX5",
        "received_at": "2026-08-08T21:00:00+00:00",
        "event_code": "TOR",
        "event_name": "Tornado Warning",
        "tier": "A",
        "matched_phrase": "tornado warning",
        "transcript_text": "a tornado warning has been issued",
    }
    event.update(overrides)
    return event


def test_transcript_only_payload_has_no_rf_source():
    """A keyword-matched (no-SAME-header) alert (fusion's `TRANSCRIPT_ONLY`
    state, design doc's live-transcription addendum to §5) must never
    reach dispatcher's stage 1 -- an unguarded, fuzzily keyword-matched
    transcript reaching the mesh is exactly the failure mode design doc §6
    calls out as this system's worst. `parse_rf_source` already delivers
    this guarantee for free: a TRANSCRIPT_ONLY alert's only source has
    `kind == "TRANSCRIPT"`, never "RF", so this must return `None` here
    the same way it already does for a pure API_ONLY alert above."""
    payload = {
        "id": "abc123",
        "state": "TRANSCRIPT_ONLY",
        "sources": [{"event": _keyword_event(), "kind": "TRANSCRIPT"}],
    }
    assert parse_rf_source(payload) is None
