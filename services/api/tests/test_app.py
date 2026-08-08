import json

from fastapi.testclient import TestClient

from api.app import create_app
from api import status as status_module
from api.sse import Broadcaster

from fake_pool import FakePool


class FakeRedis:
    def __init__(self, store=None):
        self.store = store or {}

    async def get(self, key):
        return self.store.get(key)

    async def keys(self, pattern):
        prefix = pattern.rstrip("*")
        return [k for k in self.store if k.startswith(prefix)]


def _client(pool=None, redis=None, broadcaster=None, static_dir=None):
    app = create_app(pool or FakePool(), redis or FakeRedis(), broadcaster, static_dir=static_dir)
    return TestClient(app)


def test_get_alerts_returns_rows_from_the_pool():
    pool = FakePool(fetch_results=[[{"id": "a1", "state": "RF_ONLY", "sources": json.dumps([])}]])
    response = _client(pool=pool).get("/alerts")

    assert response.status_code == 200
    body = response.json()
    assert body == [{"id": "a1", "state": "RF_ONLY", "sources": []}]


def test_get_alerts_passes_state_filter_through():
    pool = FakePool(fetch_results=[[]])
    _client(pool=pool).get("/alerts?state=CONFIRMED&limit=5")

    query, args = pool.fetch_calls[0]
    assert "WHERE state = $1" in query
    assert args == ("CONFIRMED", 5)


def test_get_alerts_rejects_limit_over_1000():
    response = _client().get("/alerts?limit=5000")
    assert response.status_code == 422


def test_get_health_returns_rows_from_the_pool():
    pool = FakePool(fetch_results=[[{"site": "home", "channel": "WX5", "dead": False}]])
    response = _client(pool=pool).get("/health")
    assert response.json() == [{"site": "home", "channel": "WX5", "dead": False}]


def test_get_spectrum_for_a_known_site():
    redis = FakeRedis({"tocsin:spectrum:home": json.dumps({"site": "home", "bin_power_db": [-40.0]})})
    response = _client(redis=redis).get("/spectrum/home")
    assert response.status_code == 200
    assert response.json()["site"] == "home"


def test_get_spectrum_for_an_unknown_site_is_404():
    response = _client().get("/spectrum/nowhere")
    assert response.status_code == 404


def test_get_spectrum_sites_lists_known_sites():
    redis = FakeRedis({"tocsin:spectrum:home": "{}", "tocsin:spectrum:office": "{}"})
    response = _client(redis=redis).get("/spectrum")
    assert set(response.json()) == {"home", "office"}


def test_get_stats_computes_divergence_rate():
    pool = FakePool(
        fetch_results=[
            [
                {"state": "RF_ONLY", "count": 2},
                {"state": "API_ONLY", "count": 1},
                {"state": "CONFIRMED", "count": 7},
            ]
        ]
    )
    response = _client(pool=pool).get("/stats")
    body = response.json()
    assert body["total"] == 10
    assert body["divergence_rate"] == 0.3


def test_get_stats_with_no_alerts_does_not_divide_by_zero():
    pool = FakePool(fetch_results=[[], []])  # state counts, then dispatch summary
    response = _client(pool=pool).get("/stats")
    assert response.json()["divergence_rate"] == 0.0


def test_get_stats_includes_the_dispatch_summary():
    """Divergence rate says whether RF and the API agree; this says
    whether anything actually left the building. Both belong on /stats."""
    pool = FakePool(
        fetch_results=[
            [{"state": "CONFIRMED", "count": 2}],
            [
                {"sent": True, "reason": "serial", "count": 3},
                {"sent": False, "reason": "skipped_rate_limited", "count": 1},
            ],
        ]
    )
    body = _client(pool=pool).get("/stats").json()

    assert body["dispatch"]["sent"] == 3
    assert body["dispatch"]["skipped"] == 1
    assert body["dispatch"]["by_reason"]["skipped_rate_limited"] == 1


def test_events_route_is_registered_as_sse():
    # Not exercised as a live HTTP stream here: /events' generator runs
    # forever until the client disconnects, and TestClient's stream()
    # doesn't reliably cancel that on context exit (confirmed by hand --
    # it hangs). The actual pub/sub logic (Broadcaster) is fully covered
    # by test_sse.py instead; this just confirms the route exists.
    app = _client().app
    route = next(r for r in app.routes if getattr(r, "path", None) == "/events")
    assert route.methods == {"GET"}


def test_cors_allows_any_origin_for_browser_reads():
    response = _client().get("/alerts", headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "*"


def test_with_no_static_dir_root_is_a_plain_404():
    # Formerly nginx's job (web/nginx.conf); with no built web/dist
    # mounted (e.g. plain `uv run api` dev use), "/" simply isn't a route.
    response = _client().get("/")
    assert response.status_code == 404


def test_static_dir_serves_the_built_spa_at_root(tmp_path):
    (tmp_path / "index.html").write_text("<html>tocsin</html>")
    response = _client(static_dir=tmp_path).get("/")
    assert response.status_code == 200
    assert "tocsin" in response.text


def test_static_dir_does_not_shadow_api_routes(tmp_path):
    # An /alerts/index.html or similar under dist would be unusual, but the
    # point is the API route registered above the mount always wins for
    # its exact path -- see app.py's comment on mount ordering.
    (tmp_path / "index.html").write_text("<html>tocsin</html>")
    pool = FakePool(fetch_results=[[{"id": "a1", "state": "RF_ONLY", "sources": json.dumps([])}]])
    response = _client(pool=pool, static_dir=tmp_path).get("/alerts")
    assert response.status_code == 200
    assert response.json() == [{"id": "a1", "state": "RF_ONLY", "sources": []}]


def _config(**overrides):
    from api.config import ApiConfig

    defaults = dict(
        postgres_dsn=None,
        redis_url="redis://redis:6379/0",
        consumer_name="api",
        host="0.0.0.0",
        port=8000,
        static_dir=None,
        mode="offgrid",
        data_dir=None,
        captures_dir=None,
        icecast_host="icecast",
        icecast_port=8000,
        icecast_public_url=None,
    )
    defaults.update(overrides)
    return ApiConfig(**defaults)


def _configured_client(pool=None, redis=None, http_get=None, **config_overrides):
    app = create_app(
        pool or FakePool(),
        redis or FakeRedis(),
        config=_config(**config_overrides),
        http_get=http_get or (lambda url: None),
    )
    return TestClient(app)


def test_get_system_reports_the_mode():
    """The UI cannot render an empty API-source column honestly without
    this: empty means "no network by design" offgrid and "the poller is
    broken" hybrid."""
    body = _configured_client(mode="hybrid").get("/system").json()
    assert body["mode"] == "hybrid"


def test_get_services_lists_expected_services_as_down_when_redis_is_empty():
    body = _configured_client().get("/services").json()

    assert {row["service"] for row in body} == set(status_module.EXPECTED_ALWAYS)
    assert all(row["status"] == "down" for row in body)


def test_get_reference_serves_the_checked_in_data():
    from pathlib import Path

    data_dir = Path(__file__).resolve().parents[3] / "data"
    body = _configured_client(data_dir=data_dir).get("/reference").json()

    assert body["event_codes"]["TOR"]["tier"] == "A"
    assert body["counties"]["41051"]["county"] == "Multnomah"


def test_get_streams_reports_icecast_unreachable_without_erroring():
    async def failing_get(url):
        raise OSError("connection refused")

    body = _configured_client(http_get=failing_get).get("/streams").json()

    assert body["icecast_reachable"] is False
    assert body["streams"] == []


def test_get_streams_lists_mounts_from_live_audios_heartbeat():
    heartbeat = json.dumps(
        {
            "service": "live_audio",
            "updated_at": "2026-08-08T21:00:00+00:00",
            "detail": {"mounts": [{"site": "home", "channel": "WX1", "mount": "/home-WX1.ogg", "alive": True}]},
        }
    )

    async def icecast_get(url):
        return json.dumps({"icestats": {"source": {"listenurl": "http://icecast:8000/home-WX1.ogg", "listeners": 4}}})

    client = _configured_client(redis=FakeRedis({"tocsin:status:live_audio": heartbeat}), http_get=icecast_get)
    body = client.get("/streams").json()

    assert body["icecast_reachable"] is True
    assert body["streams"][0]["url"] == "http://icecast:8000/home-WX1.ogg"
    assert body["streams"][0]["listeners"] == 4
    assert body["streams"][0]["on_air"] is True


def test_get_transcripts_filters_by_raw_header():
    """raw_header is the only identifier shared between fusion's alert and
    stt_worker's transcript -- it's how the UI attaches one to the other."""
    pool = FakePool(fetch_results=[[]])
    _configured_client(pool=pool).get("/transcripts?raw_header=ZCZC-WXR-TOR-041051%2B0030-2210300-KPTL%2FNWS-")

    query, args = pool.fetch_calls[0]
    assert "WHERE raw_header = $1" in query
    assert args[0] == "ZCZC-WXR-TOR-041051+0030-2210300-KPTL/NWS-"


def test_get_dispatches_returns_rows():
    pool = FakePool(fetch_results=[[{"reason": "serial", "sent": True}]])
    body = _configured_client(pool=pool).get("/dispatches").json()
    assert body == [{"reason": "serial", "sent": True}]


def test_get_health_history_rejects_an_absurd_window():
    assert _configured_client().get("/health/history?since_seconds=99999999").status_code == 422


def test_capture_download_rejects_a_path_traversal(tmp_path):
    """wav_path reaches this endpoint from a Redis payload, so treating it
    as a trusted filesystem path would make /captures an arbitrary-file
    read on the container."""
    (tmp_path / "ok.wav").write_bytes(b"RIFF")
    secret = tmp_path.parent / "secret.wav"
    secret.write_bytes(b"nope")

    client = _configured_client(captures_dir=tmp_path)

    assert client.get("/captures/ok.wav").status_code == 200
    assert client.get("/captures/..%2Fsecret.wav").status_code == 404
    assert client.get("/captures/nonexistent.wav").status_code == 404


def test_captures_are_404_when_not_configured():
    assert _configured_client().get("/captures/anything.wav").status_code == 404
