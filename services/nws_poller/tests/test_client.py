import pytest

from nws_poller.client import ALERTS_ACTIVE_URL, FetchResult, NwsAlertsClient


class FakeResponse:
    def __init__(self, status_code=200, json_body=None, headers=None):
        self.status_code = status_code
        self._json_body = json_body or {}
        self.headers = headers or {}

    def json(self):
        return self._json_body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeGet:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return self.response


def test_missing_user_agent_raises():
    with pytest.raises(ValueError):
        NwsAlertsClient(user_agent="")


def test_fetch_sends_user_agent_and_area():
    fake_get = FakeGet(FakeResponse(200, {"features": []}, headers={"ETag": "abc"}))
    client = NwsAlertsClient(user_agent="tocsin (test@example.com)", get=fake_get)

    result = client.fetch("OR")

    assert fake_get.calls[0]["url"] == ALERTS_ACTIVE_URL
    assert fake_get.calls[0]["params"] == {"area": "OR"}
    assert fake_get.calls[0]["headers"]["User-Agent"] == "tocsin (test@example.com)"
    assert "If-None-Match" not in fake_get.calls[0]["headers"]
    assert result == FetchResult(not_modified=False, etag="abc", features=())


def test_fetch_sends_if_none_match_when_etag_given():
    fake_get = FakeGet(FakeResponse(304, headers={}))
    client = NwsAlertsClient(user_agent="tocsin (test@example.com)", get=fake_get)

    result = client.fetch("OR", etag="abc")

    assert fake_get.calls[0]["headers"]["If-None-Match"] == "abc"
    assert result == FetchResult(not_modified=True, etag="abc", features=())


def test_fetch_returns_features_on_200():
    feature = {"type": "Feature", "properties": {"id": "x"}}
    fake_get = FakeGet(FakeResponse(200, {"features": [feature]}, headers={"ETag": "v2"}))
    client = NwsAlertsClient(user_agent="tocsin (test@example.com)", get=fake_get)

    result = client.fetch("OR", etag="v1")

    assert result.not_modified is False
    assert result.etag == "v2"
    assert result.features == (feature,)


def test_fetch_raises_on_http_error():
    fake_get = FakeGet(FakeResponse(500))
    client = NwsAlertsClient(user_agent="tocsin (test@example.com)", get=fake_get)

    with pytest.raises(RuntimeError):
        client.fetch("OR")
