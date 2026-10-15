"""Optional API key: off by default, header/bearer everywhere, ?api_key= only where a browser cannot set headers."""
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import is_api_path, key_matches

from fake_pool import FakePool
from test_app import FakeRedis, _config, _configured_client


async def _no_icecast(url):
    return None


def _client(keys=("s3cret",), **overrides):
    return _configured_client(api_keys=keys, open_audio_stream=_no_icecast, **overrides)


def test_no_key_configured_leaves_every_route_open():
    assert _client(keys=()).get("/alerts").status_code == 200


def test_missing_or_wrong_key_is_rejected_with_401():
    client = _client()
    assert client.get("/alerts").status_code == 401
    assert client.get("/alerts", headers={"X-API-Key": "nope"}).status_code == 401
    body = client.get("/alerts").json()
    assert body == {"detail": "API key required"}


def test_header_and_bearer_both_work_and_any_listed_key_is_accepted():
    client = _client(keys=("old-key", "new-key"))
    assert client.get("/alerts", headers={"X-API-Key": "old-key"}).status_code == 200
    assert client.get("/alerts", headers={"Authorization": "Bearer new-key"}).status_code == 200


def test_query_key_only_where_a_browser_cannot_send_headers():
    client = _client()
    assert client.get("/alerts?api_key=s3cret").status_code == 401        # JSON routes: header only
    assert client.get("/captures/x.wav?api_key=s3cret").status_code != 401  # 404 (no such file) means past the gate
    assert client.get("/stream/PDX-WX7.ogg?api_key=s3cret").status_code != 401


def test_spa_files_stay_open_so_the_page_can_load_and_ask_for_the_key(tmp_path):
    (tmp_path / "index.html").write_text("<html>tocsin</html>")
    app = create_app(FakePool(), FakeRedis(), config=_config(api_keys=("s3cret",)), static_dir=tmp_path)
    client = TestClient(app)
    assert client.get("/").status_code == 200
    assert client.get("/alerts").status_code == 401


def test_cors_preflight_is_not_blocked_and_a_401_still_carries_cors_headers():
    client = _client()
    pre = client.options("/alerts", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert pre.status_code == 200
    denied = client.get("/alerts", headers={"Origin": "http://localhost:5173"})
    assert denied.status_code == 401 and denied.headers.get("access-control-allow-origin") == "*"


def test_is_api_path_matches_routes_not_spa_assets():
    assert is_api_path("/alerts") and is_api_path("/events") and is_api_path("/stream/PDX-WX7.ogg")
    assert not is_api_path("/") and not is_api_path("/assets/index-abc.js") and not is_api_path("/alertsfoo")


def test_key_matches_is_exact():
    assert key_matches("abc", ("abc",)) and not key_matches("abcd", ("abc",)) and not key_matches("", ("abc",))
    assert not key_matches(None, ("abc",))
