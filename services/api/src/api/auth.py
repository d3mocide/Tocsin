"""Optional API-key gate for the JSON/SSE/audio routes.

Off unless `API_KEY` is set, so every existing deployment (localhost/LAN, the SPA served from this same
process) behaves exactly as before. With a key set, the data routes below need it as `X-API-Key: <key>` or
`Authorization: Bearer <key>`; the SPA's own files stay open so the page can load and ask for the key.

The page itself needs no key: a browser stamps every request the page makes to its own server with
`Sec-Fetch-Site: same-origin`, which page scripts cannot forge, so those are let through (`API_KEY_UI_OPEN`,
default on). Be clear about what that is: it keeps other websites and ordinary clients out, but anyone on your
network who deliberately sets that header by hand is let in too -- the key is a gate for programs, not a login.
Set `API_KEY_UI_OPEN=false` to make the page ask for the key as well.

`EventSource` and `<audio>` cannot set headers, so `/events`, `/stream/` and `/captures/` additionally accept
`?api_key=`. That puts the key in the URL (and in any access log that records it), so prefer the header
everywhere else; several comma-separated keys are accepted so one can be rotated without downtime.

Pure ASGI, not BaseHTTPMiddleware: the latter wraps responses in a way that buffers and mishandles the
never-ending SSE and audio streams.
"""

from __future__ import annotations

import hmac
import json
from urllib.parse import parse_qs

API_ROUTES = (
    "/alerts", "/health", "/transcripts", "/dispatches", "/spectrum", "/stats", "/system",
    "/services", "/reference", "/streams", "/stream", "/captures", "/events",
)
QUERY_KEY_ROUTES = ("/events", "/stream", "/captures")


def _under(path: str, routes: tuple[str, ...]) -> bool:
    # A route or anything below it ("/health/history", "/stream/PDX-WX7.ogg"), never a mere text prefix
    # ("/alertsfoo" is not "/alerts").
    return any(path == route or path.startswith(route + "/") for route in routes)


def is_api_path(path: str) -> bool:
    return _under(path, API_ROUTES)


def same_origin_browser(scope) -> bool:
    """True for a request the Tocsin web page made to its own server (see the module docstring)."""
    return any(k == b"sec-fetch-site" and v == b"same-origin" for k, v in scope["headers"])


def key_matches(candidate: str | None, keys: tuple[str, ...]) -> bool:
    if not candidate:
        return False
    given = candidate.encode()
    # Compare against every key (no early exit) so timing does not reveal which one was close.
    return any([hmac.compare_digest(given, key.encode()) for key in keys])


def _presented_key(scope) -> str | None:
    headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
    if headers.get("x-api-key"):
        return headers["x-api-key"]
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    if _under(scope["path"], QUERY_KEY_ROUTES):
        values = parse_qs(scope.get("query_string", b"").decode("latin-1")).get("api_key")
        if values:
            return values[0]
    return None


class ApiKeyMiddleware:
    def __init__(self, app, keys: tuple[str, ...], ui_open: bool = True):
        self.app = app
        self.keys = keys
        self.ui_open = ui_open

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or not self.keys
            or scope["method"] == "OPTIONS"          # CORS preflight carries no credentials
            or not is_api_path(scope["path"])
            or (self.ui_open and same_origin_browser(scope))
            or key_matches(_presented_key(scope), self.keys)
        ):
            await self.app(scope, receive, send)
            return
        body = json.dumps({"detail": "API key required"}).encode()
        await send({"type": "http.response.start", "status": 401, "headers": [
            (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
            (b"www-authenticate", b"ApiKey"),
        ]})
        await send({"type": "http.response.body", "body": body})
