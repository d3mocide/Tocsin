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


def test_the_web_page_own_requests_are_let_through_without_a_key():
    client = _client()
    page = {"Sec-Fetch-Site": "same-origin"}
    assert client.get("/alerts", headers=page).status_code == 200


def test_other_origins_and_plain_clients_still_need_the_key():
    client = _client()
    for site in ("cross-site", "same-site", "none"):                         # another website, a sibling, a typed URL
        assert client.get("/alerts", headers={"Sec-Fetch-Site": site}).status_code == 401
    assert client.get("/alerts").status_code == 401                          # curl / Vertex send no such header


def test_ui_open_can_be_turned_off_so_the_page_needs_the_key_too():
    client = _client(api_key_ui_open=False)
    assert client.get("/alerts", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 401
    assert client.get("/alerts", headers={"Sec-Fetch-Site": "same-origin", "X-API-Key": "s3cret"}).status_code == 200


async def _run_through(scope_headers, path="/events", **mw):
    """Drive the middleware directly: True if the request reached the app, else the status it was answered with.
    (TestClient cannot be used on /events: the stream never ends.)"""
    from api.auth import ApiKeyMiddleware
    reached, sent = [], []

    async def app(scope, receive, send):
        reached.append(True)

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "GET", "path": path, "query_string": b"", "headers": scope_headers}
    await ApiKeyMiddleware(app, ("s3cret",), **mw)(scope, None, send)
    return True if reached else sent[0]["status"]


async def test_the_page_may_open_the_event_stream_but_a_bare_client_may_not():
    assert await _run_through([(b"sec-fetch-site", b"same-origin")]) is True
    assert await _run_through([]) == 401
    assert await _run_through([(b"sec-fetch-site", b"cross-site")]) == 401
    assert await _run_through([(b"x-api-key", b"s3cret")]) is True
    assert await _run_through([(b"sec-fetch-site", b"same-origin")], ui_open=False) == 401
