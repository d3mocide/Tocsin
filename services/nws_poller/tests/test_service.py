from nws_poller.client import FetchResult
from nws_poller.service import Poller

from test_parser import _feature


class FakeClient:
    def __init__(self, results_by_area: dict[str, list[FetchResult]]):
        self._results_by_area = results_by_area
        self.calls = []

    def fetch(self, area, etag=None):
        self.calls.append((area, etag))
        results = self._results_by_area[area]
        return results.pop(0)


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
