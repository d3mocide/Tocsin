# fusion

Correlates SAME/NWR events (from `same_decoder`, via the `tocsin:same_events`
Redis Stream) with NWS CAP alerts (from `nws_poller`, via `tocsin:cap_alerts`)
using the mapping in `data/same_to_cap.yaml`, without hard-merging the two
sources -- one `Alert` with a `sources[]` array and an `RF_ONLY` /
`API_ONLY` / `CONFIRMED` state. Confidence is mode-relative (design doc
§5): deployment mode is an input to the confidence calculation, not just
to which sources are active. Runs in both `offgrid` and `hybrid` --
off-grid, every alert simply stays `RF_ONLY` by design. Publishes every
canonical Alert to the `tocsin:alerts` Redis Stream (`redis_sink.py`) for
`dispatcher` (Phase 6) to consume.

## Status

Implemented and unit tested: the event-code -> CAP-event-text mapping
loader (`mapping.py`), the pure correlation predicate -- event-code match
AND FIPS overlap AND time-window match (`correlator.py`), mode-relative
confidence (`confidence.py`), the in-memory correlation state machine
(`store.py`), the Redis Streams consumer-group wiring for both inbound
streams (`redis_bus.py`), and the outbound `tocsin:alerts` producer
(`redis_sink.py`) -- including crash-recovery replay tested against a
faithful in-memory fake (no real Redis in the authoring sandbox). Test
fixtures (`tests/fixtures.py`) cover true matches, near-misses (right
event/wrong county, wrong event/right county, outside the time-window
tolerance), and both unmatched states -- the roadmap's stated Phase 5 exit
criteria.

**Known gaps, not yet handled** (see `store.py`'s and `redis_bus.py`'s own
docstrings for the full reasoning):
- A second SAME event or CAP update arriving for an already-`CONFIRMED`
  alert opens a *new* Alert rather than attaching to the existing one
  (multi-site RF-RF correlation and CAP "Update" reissues aren't part of
  the design doc's stated SAME<->CAP correlation key).
- Consumer-group durability is "at least once": a crash between processing
  and acking can replay (and therefore double-ingest) one event on
  restart. Accepted tradeoff per the design doc ("resumes... rather than
  losing an alert"), not silently ignored.
- Not verified against real Redis, or a live `same-decoder`/`nws-poller`
  pair -- verified against fixtures and a faithful in-memory fake only.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `TOCSIN_MODE` | `offgrid` | Input to mode-relative confidence (design doc §5). |
| `TOCSIN_DATA_DIR` | repo-root `data/` | Directory containing `same_to_cap.yaml`. |
| `FUSION_REDIS_URL` | `redis://redis:6379/0` | Redis connection URL for both stream consumption and the consumer group. |
| `FUSION_CONSUMER_NAME` | `fusion` | Redis consumer-group consumer name. Fixed by default, not hostname-derived -- see `__init__.py`'s comment on why a stable name matters for crash recovery across container recreation. |

## Development

```sh
uv sync
uv run pytest
```
