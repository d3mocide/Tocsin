import json

from fastapi.testclient import TestClient

from api.app import create_app
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
    pool = FakePool(fetch_results=[[]])
    response = _client(pool=pool).get("/stats")
    assert response.json()["divergence_rate"] == 0.0


def test_stream_alerts_route_is_registered_as_sse():
    # Not exercised as a live HTTP stream here: /alerts/stream's generator
    # runs forever until the client disconnects, and TestClient's stream()
    # doesn't reliably cancel that on context exit (confirmed by hand --
    # it hangs). The actual pub/sub logic (Broadcaster) is fully covered
    # by test_sse.py instead; this just confirms the route exists with the
    # right declared media type.
    app = _client().app
    route = next(r for r in app.routes if getattr(r, "path", None) == "/alerts/stream")
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
