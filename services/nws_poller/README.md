# nws-poller

Polls `api.weather.gov/alerts/active` with ETag-conditional requests, one
request per configured area (the API's `area` parameter takes exactly one
state/marine-area code per call -- confirmed against the API's own OpenAPI
spec) plus, if `NWS_POLLER_ZONES` is set, one additional combined request
covering every configured public-forecast zone (`zone` *is* a repeatable
parameter -- see `client.py`'s docstring), and publishes new/updated CAP
alerts to Redis Streams for `fusion`. `hybrid` only -- disabled entirely in
`offgrid` mode (design doc §8).

Zones are additive, not a replacement for areas: `NWS_POLLER_AREAS` stays
required and keeps polling whole states/marine areas, and `NWS_POLLER_ZONES`
is an optional narrower filter on top for operators who only care about a
handful of specific zones (find codes at weather.gov/pimar/PubZone). Since
zones are meant to sit inside the configured areas' geography, the same CAP
alert routinely comes back from both requests -- `Poller` shares one dedup
tracker across every area and the zone request rather than tracking "seen"
per request target, so `fusion` only sees it once. This also fixed a
latent case that predates zone support: two overlapping areas (e.g. a
marine warning matching both `OR` and `WA`) used to reach `fusion` twice,
which had no dedup of its own to catch it (`fusion/store.py`'s
`ingest_cap` mints a new `Alert` for any CAP alert that doesn't match an
open RF-only one -- see that module for why one is out of scope here).

No `compose.yaml` service or Dockerfile of its own: this project ships
inside `fusion`'s container image (`../fusion/Dockerfile`, build context
the repo root) as a second, independent uv project/venv, started by
`../fusion/entrypoint.sh` only when `TOCSIN_MODE=hybrid` -- that
`TOCSIN_MODE` check is what enforces "disabled entirely in `offgrid`"
now, replacing the compose-profile gate this service used to have when
it was its own container. Still fully independent of `fusion` at the
Python level (own `pyproject.toml`, own tests, no cross-import) --
`../fusion/README.md`'s "Container" section has the full picture.

## Status

Implemented and unit tested: the HTTP client (`client.py`, ETag-conditional
`If-None-Match`/304 handling, one request per area plus one combined
request for `NWS_POLLER_ZONES`), the GeoJSON-feature -> `CapAlert` parser
(`parser.py`), the `(id, sent)` dedup tracker that stops an unchanged
active alert from being re-emitted every poll cycle -- one instance shared
across every area and the zone request, not one per request target, so an
alert both requests return is still only new once (`tracker.py`,
`service.py`) -- the Redis Streams sink (`redis_sink.py`), and the polling
pipeline (`service.py`). Tested against a fake HTTP getter and a fake Redis
client -- no real network access or Redis instance in the authoring
sandbox.

**Not yet verified:** against the real `api.weather.gov` endpoint (response
shape was confirmed against the API's published OpenAPI spec, not a live
call) or a real Redis instance.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `NWS_POLLER_USER_AGENT` | *(required)* | NWS API requires a descriptive User-Agent identifying the application; refuses to start without one. |
| `NWS_POLLER_AREAS` | *(required)* | Comma-separated state/marine-area codes to poll, e.g. `OR,WA`. One HTTP request per area per cycle. |
| `NWS_POLLER_ZONES` | *(unset)* | Comma-separated public-forecast zone codes, e.g. `ORZ006,ORZ005`. Optional and additive to `NWS_POLLER_AREAS`, not a replacement -- one combined request per cycle covering every zone listed. |
| `NWS_POLLER_INTERVAL_SECONDS` | `60` | Poll interval. |
| `NWS_POLLER_REDIS_URL` | *(unset -- logs to stdout)* | Redis connection URL. When unset, alerts are logged as JSON instead of published, for local/dev runs without a Redis instance. |

## Development

```sh
uv sync
uv run pytest
```
