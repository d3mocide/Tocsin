# dispatcher

Consumes canonical Alerts from `fusion`'s `tocsin:alerts` Redis Stream and
dispatches a deterministic, zero-dependency stage-1 message over
Meshtastic serial the moment a Tier A SAME header decodes (design doc §7,
§10 milestone 6). Stage 2 (LLM enrichment) and the Meshtastic MQTT
ack-fallback leg are Phase 7, not yet built.

```
TOR WARN | Multnomah,Clackamas OR | exp 2145Z | RF
```

## Status

Implemented and unit tested: the FIPS -> county/state lookup (`fips.py`,
loads `data/fips.csv`), the stage-1 template builder with byte-budget
truncation (`message.py`), near-duplicate suppression (`dedup.py`), an
in-process token bucket (`rate_limit.py`), Redis-persisted idempotency so
a restart doesn't re-send (`idempotency.py`, keyed on the SAME header's
own `raw_header` since SAME carries no ETN -- see its docstring), a thin
injectable wrapper around the real `meshtastic` PyPI package's serial
interface (`meshtastic_serial.py`, verified against the library's actual
source for `sendText`'s `onResponse` callback shape, not guessed), the
Redis consumer-group wiring over `tocsin:alerts` (`redis_bus.py`, same
crash-replay pattern as `fusion.redis_bus`), and the full pipeline wiring
(`service.py`: tier gate -> dedup -> rate limit -> idempotency claim ->
send, in that specific order -- see `service.py`'s own docstring for why
idempotency is claimed last, not first).

**Known gaps, not yet handled:**
- No MQTT ack-fallback (Phase 7) -- if the serial send throws or times out
  waiting for an ack, the message simply isn't retried by another path.
  The idempotency key is still claimed at that point (see
  `service.py`'s docstring), so a transient serial failure means that
  exact alert won't be retried until its 24h claim expires.
- Only Tier A alerts reach the mesh. Tier B (`data/same_event_codes.yaml`:
  "MQTT only") has no MQTT egress built yet -- not clearly scoped to a
  named phase in `docs/design/roadmap.md` as of this writing (Phase 7 only
  names the Meshtastic MQTT *ack-fallback* leg specifically). Tier B/C
  alerts are logged as skipped, not queued.
- A SAME header whose FIPS codes span more than one state only shows the
  first state seen in the stage-1 message (`message.py`).
- Not verified against a real Meshtastic node, real Redis, or real
  `fusion` output -- verified against fixtures and fakes only (no serial
  hardware, no Redis instance in this authoring sandbox).

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `TOCSIN_DATA_DIR` | repo-root `data/` | Directory containing `fips.csv`. |
| `DISPATCHER_REDIS_URL` | `redis://redis:6379/0` | Redis connection URL (stream consumption + idempotency keys). |
| `DISPATCHER_CONSUMER_NAME` | `dispatcher` | Redis consumer-group consumer name. Fixed, not hostname-derived -- see `__init__.py`'s comment (same reasoning as `fusion`'s). |
| `MESHTASTIC_SERIAL_DEV_PATH` | *(unset -- autodetect)* | Serial device path, e.g. `/dev/ttyUSB0`. Only needed if more than one serial device is attached to the host. |

## Development

```sh
uv sync
uv run pytest
```
