# nws-poller

Polls `api.weather.gov/alerts/active` with ETag-conditional requests, one
request per configured area (the API's `area` parameter takes exactly one
state/marine-area code per call -- confirmed against the API's own OpenAPI
spec), and publishes new/updated CAP alerts to Redis Streams for `fusion`.
`hybrid` profile only -- disabled entirely in `offgrid` mode (design doc
§8) by simply not being started under that compose profile.

## Status

Implemented and unit tested: the HTTP client (`client.py`, ETag-conditional
`If-None-Match`/304 handling, one area per request), the GeoJSON-feature ->
`CapAlert` parser (`parser.py`), the `(id, sent)` dedup tracker that stops
an unchanged active alert from being re-emitted every poll cycle
(`tracker.py`), the Redis Streams sink (`redis_sink.py`), and the polling
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
| `NWS_POLLER_INTERVAL_SECONDS` | `60` | Poll interval. |
| `NWS_POLLER_REDIS_URL` | *(unset -- logs to stdout)* | Redis connection URL. When unset, alerts are logged as JSON instead of published, for local/dev runs without a Redis instance. |

## Development

```sh
uv sync
uv run pytest
```
