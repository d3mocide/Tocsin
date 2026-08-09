"""HTTP client for `api.weather.gov/alerts/active`, ETag-conditional per
area or zone set (design doc §5, §10 milestone 5).

The NWS API requires a descriptive `User-Agent` header (its own docs: "A
User Agent is required to identify your application") and its `area` query
parameter is typed as a single StateTerritoryCode/MarineAreaCode, not an
array -- confirmed against api.weather.gov's own OpenAPI spec (`zone`
accepts repeated values, `area` does not). Polling N areas therefore means
N requests, one ETag tracked per area -- see `service.py`.

`zone`, by contrast, *is* an array: a whole `NWS_POLLER_ZONES` list (public
forecast zone codes, e.g. `ORZ006`) goes out as one request with `zone`
repeated once per code, matched by one ETag, since the API returns the
union of alerts across every zone given. This exists to poll a tighter
area than a whole state -- see `service.py`'s `Poller` for how it composes
with `fetch`'s per-area calls.

The GET call is injectable (same pattern as `same_decoder.multimon`'s
injectable subprocess command) so this is testable without real network
access, which this authoring sandbox may not reliably have.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

import requests

ALERTS_ACTIVE_URL = "https://api.weather.gov/alerts/active"
DEFAULT_TIMEOUT_SECONDS = 10.0


class HttpResponse(Protocol):
    status_code: int
    headers: dict

    def json(self) -> dict: ...
    def raise_for_status(self) -> None: ...


GetFn = Callable[..., HttpResponse]


@dataclass(frozen=True)
class FetchResult:
    not_modified: bool
    etag: str | None
    features: tuple[dict, ...]


class NwsAlertsClient:
    def __init__(
        self,
        user_agent: str,
        get: GetFn = requests.get,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        if not user_agent:
            raise ValueError(
                "user_agent is required by api.weather.gov -- set NWS_POLLER_USER_AGENT"
            )
        self._user_agent = user_agent
        self._get = get
        self._timeout = timeout_seconds

    def fetch(self, area: str, etag: str | None = None) -> FetchResult:
        """Fetches active alerts for one area. `etag` is caller-managed
        (the caller keeps the last-seen value per area and passes it back
        in) rather than stored here -- `service.py` is also the thing
        deciding what to do with a stale tracker, so keeping ETag state in
        one place avoids two sources of truth for the same fact."""
        return self._fetch({"area": area}, etag)

    def fetch_zones(self, zones: list[str], etag: str | None = None) -> FetchResult:
        """Fetches active alerts for a set of forecast zones in one request
        (unlike `area`, `zone` is a repeatable query parameter -- see this
        module's docstring). `zones` order doesn't matter to the API, but
        `service.py` passes the same list/order back in each cycle so the
        ETag it tracks stays meaningful."""
        return self._fetch({"zone": zones}, etag)

    def _fetch(self, params: dict, etag: str | None) -> FetchResult:
        headers = {"User-Agent": self._user_agent, "Accept": "application/geo+json"}
        if etag:
            headers["If-None-Match"] = etag
        response = self._get(ALERTS_ACTIVE_URL, params=params, headers=headers, timeout=self._timeout)
        if response.status_code == 304:
            return FetchResult(not_modified=True, etag=etag, features=())
        response.raise_for_status()
        body = response.json()
        new_etag = response.headers.get("ETag", etag)
        return FetchResult(not_modified=False, etag=new_etag, features=tuple(body.get("features", [])))
