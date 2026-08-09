from nws_poller.client import FetchResult
from nws_poller.service import Poller

from test_parser import _feature


class FakeClient:
    def __init__(self, results_by_area: dict[str, list[FetchResult]], zone_results: list[FetchResult] | None = None):
        self._results_by_area = results_by_area
        self._zone_results = zone_results or []
        self.calls = []
        self.zone_calls = []

    def fetch(self, area, etag=None):
        self.calls.append((area, etag))
        results = self._results_by_area[area]
        return results.pop(0)

    def fetch_zones(self, zones, etag=None):
        self.zone_calls.append((zones, etag))
        return self._zone_results.pop(0)


class FakeSink:
    def __init__(self):
        self.alerts = []

    def record(self, alert):
        self.alerts.append(alert)


def test_poll_once_emits_parsed_alerts_per_area():
    feature = _feature()
    client = FakeClient(
        {
            "OR": [FetchResult(not_modified=False, etag="e1", features=(feature,))],
            "WA": [FetchResult(not_modified=False, etag="e2", features=())],
        }
    )
    sink = FakeSink()
    poller = Poller(client, ["OR", "WA"], sink=sink)

    emitted = poller.poll_once()

    assert emitted == 1
    assert len(sink.alerts) == 1
    assert sink.alerts[0].id == feature["properties"]["id"]


def test_not_modified_emits_nothing_and_keeps_etag():
    client = FakeClient({"OR": [FetchResult(not_modified=True, etag="e1", features=())]})
    sink = FakeSink()
    poller = Poller(client, ["OR"], sink=sink)

    emitted = poller.poll_once()

    assert emitted == 0
    assert sink.alerts == []


def test_second_poll_reuses_stored_etag():
    feature = _feature()
    client = FakeClient(
        {
            "OR": [
                FetchResult(not_modified=False, etag="e1", features=(feature,)),
                FetchResult(not_modified=True, etag="e1", features=()),
            ]
        }
    )
    poller = Poller(client, ["OR"], sink=FakeSink())

    poller.poll_once()
    poller.poll_once()

    assert client.calls == [("OR", None), ("OR", "e1")]


def test_unchanged_alert_is_not_re_emitted_across_polls():
    feature = _feature()
    client = FakeClient(
        {
            "OR": [
                FetchResult(not_modified=False, etag="e1", features=(feature,)),
                FetchResult(not_modified=False, etag="e1", features=(feature,)),
            ]
        }
    )
    sink = FakeSink()
    poller = Poller(client, ["OR"], sink=sink)

    first = poller.poll_once()
    second = poller.poll_once()

    assert first == 1
    assert second == 0


def test_no_zones_configured_means_no_zone_request_at_all():
    client = FakeClient({"OR": [FetchResult(not_modified=False, etag="e1", features=())]})
    poller = Poller(client, ["OR"], sink=FakeSink())

    poller.poll_once()

    assert client.zone_calls == []


def test_zones_are_polled_as_one_combined_request_alongside_areas():
    feature = _feature()
    client = FakeClient(
        {"OR": [FetchResult(not_modified=False, etag="e1", features=())]},
        zone_results=[FetchResult(not_modified=False, etag="z1", features=(feature,))],
    )
    sink = FakeSink()
    poller = Poller(client, ["OR"], sink=sink, zones=["ORZ006", "ORZ005"])

    emitted = poller.poll_once()

    assert emitted == 1
    assert client.zone_calls == [(["ORZ006", "ORZ005"], None)]
    assert sink.alerts[0].id == feature["properties"]["id"]


def test_zone_etag_is_reused_and_kept_separate_from_area_etags():
    feature = _feature()
    client = FakeClient(
        {
            "OR": [
                FetchResult(not_modified=False, etag="area-e1", features=()),
                FetchResult(not_modified=True, etag="area-e1", features=()),
            ]
        },
        zone_results=[
            FetchResult(not_modified=False, etag="zone-e1", features=(feature,)),
            FetchResult(not_modified=True, etag="zone-e1", features=()),
        ],
    )
    poller = Poller(client, ["OR"], sink=FakeSink(), zones=["ORZ006"])

    poller.poll_once()
    poller.poll_once()

    assert client.calls == [("OR", None), ("OR", "area-e1")]
    assert client.zone_calls == [(["ORZ006"], None), (["ORZ006"], "zone-e1")]


def test_an_alert_matching_both_an_area_and_the_zone_set_is_emitted_once():
    """`fusion.store.ingest_cap` has no id-based dedup of its own -- every
    call that doesn't match an open RF-only alert creates a new `Alert`.
    Since `NWS_POLLER_ZONES` is a narrower filter *on top of*
    `NWS_POLLER_AREAS`, the same CAP alert routinely appears in both
    responses, so the two request targets share one dedup tracker rather
    than each independently deciding the alert is "new"."""
    feature = _feature()
    client = FakeClient(
        {"OR": [FetchResult(not_modified=False, etag="e1", features=(feature,))]},
        zone_results=[FetchResult(not_modified=False, etag="z1", features=(feature,))],
    )
    sink = FakeSink()
    poller = Poller(client, ["OR"], sink=sink, zones=["ORZ006"])

    emitted = poller.poll_once()

    assert emitted == 1
    assert len(sink.alerts) == 1


def test_two_overlapping_areas_also_share_the_dedup_tracker():
    """Pre-existing case, same fix: a marine alert matching both OR and WA
    used to be emitted twice (one independent tracker per area)."""
    feature = _feature()
    client = FakeClient(
        {
            "OR": [FetchResult(not_modified=False, etag="e1", features=(feature,))],
            "WA": [FetchResult(not_modified=False, etag="e2", features=(feature,))],
        }
    )
    sink = FakeSink()
    poller = Poller(client, ["OR", "WA"], sink=sink)

    emitted = poller.poll_once()

    assert emitted == 1
    assert len(sink.alerts) == 1
