# dispatcher

Consumes canonical Alerts from `fusion`'s `tocsin:alerts` Redis Stream and
dispatches a deterministic, zero-dependency stage-1 message the moment a
Tier A SAME header decodes (design doc §7, §10 milestone 6). Also
consumes guarded transcripts from `stt_worker`'s `tocsin:transcripts`
stream and, when LiteLLM is configured, enriches Tier A alerts with a
compressed impact clause as a second, later message (stage 2, milestone
7). Both stages send over the same dual-path Meshtastic egress: serial
primary with `wantAck`, MQTT fallback in `hybrid` mode only.

```
TOR WARN | Multnomah,Clackamas OR | exp 2145Z | RF
```

## Status

Implemented and unit tested, both stages:

**Stage 1:** the FIPS -> county/state lookup (`fips.py`, loads
`data/fips.csv`), the stage-1 template builder with byte-budget truncation
(`message.py`), near-duplicate suppression (`dedup.py`), an in-process
token bucket (`rate_limit.py`), Redis-persisted idempotency so a restart
doesn't re-send (`idempotency.py`, keyed on the SAME header's own
`raw_header` since SAME carries no ETN), and the full pipeline wiring
(`service.py`'s `Stage1Dispatcher`: tier gate -> dedup -> rate limit ->
idempotency claim -> send, in that specific order -- see `service.py`'s
own docstring for why idempotency is claimed last, not first).

**Egress (`egress/`):** a thin injectable wrapper around the real
`meshtastic` PyPI package's serial interface (`meshtastic_serial.py`,
verified against the library's actual installed source for `sendText`'s
`onResponse` callback shape, not guessed), a Meshtastic MQTT downlink
publisher (`meshtastic_mqtt.py`, verified against Meshtastic's real MQTT
integration docs -- the `msh/{region}/2/json/mqtt/` topic and JSON schema
are exact, not approximated), and `dispatch.py`'s `DualPathSender`
combining both: serial-first, MQTT fallback only when `TOCSIN_MODE=hybrid`
and a gateway node is configured (design doc §8's connectivity contract).

**Stage 2:** LiteLLM enrichment (`litellm_client.py`, standard OpenAI
chat-completions shape verified against LiteLLM's own docs, hard 3s
timeout), a Redis-persisted circuit breaker (`circuit_breaker.py`, opens
after N consecutive failures for a cooldown, recovers once the cooldown's
Redis TTL lapses), output validation distinct from `stt_worker`'s own
hallucination guard (`stage2_guard.py`: length/ASCII/no-newlines on
LiteLLM's *output*), and `service.py`'s `Stage2Dispatcher` wiring it all
together. Tests cover roadmap.md's literal Phase 7 exit criteria: a
LiteLLM failure degrades stage 2 silently without ever touching egress
(`test_stage2_dispatcher.py`), and the circuit breaker opens after N
failures and recovers once its cooldown lapses.

**Consumer-group wiring (`redis_bus.py`):** one `AlertStreamConsumer`
class serves both `tocsin:alerts` and `tocsin:transcripts`, same
crash-replay pattern as `fusion.redis_bus` (tested against a hand-written
faithful fake of Redis's stream semantics, including the actual
crash-before-ack replay scenario).

**Known gaps, not yet handled:**
- A SAME header whose FIPS codes span more than one state only shows the
  first state seen in the stage-1 message (`message.py`).
- Tier B alerts (`data/same_event_codes.yaml`: "MQTT only") still have no
  general MQTT egress path -- not clearly scoped to a named phase in
  `docs/design/roadmap.md` as of this writing (Phase 7 only names the
  Meshtastic MQTT *ack-fallback* leg, which this service does implement).
  Tier B/C alerts are logged as skipped, not queued.
- A transient failure right at the send step (serial exception, or an
  MQTT publish exception surfacing past `DualPathSender`) still means that
  exact message won't be retried until its 24h idempotency claim expires
  -- there's no *third* fallback beyond serial+MQTT. Accepted, matching
  the design doc's own framing of the MQTT leg as "a hedge... not a
  guarantee."
- Not verified against a real Meshtastic node, a real MQTT gateway
  configuration, a real LiteLLM/OpenAI-compatible endpoint, or real Redis
  -- verified against fixtures and fakes only (none of that infrastructure
  exists in this authoring sandbox).

## Dispatch log

Every stage-1 and stage-2 decision is published to the `tocsin:dispatches`
Redis Stream (`redis_sink.py`), which `api` consumes into Postgres and
serves at `GET /dispatches`.

The negative outcomes are the point. `skipped_not_tier_a`,
`skipped_duplicate`, `skipped_rate_limited`, `skipped_already_sent`,
`serial_no_ack`, and `skipped_circuit_open` are all cases where an alert
exists and nothing reached the mesh -- until this stream they were a line
on stdout and nothing else, which made "did that warning actually go out?"
unanswerable without reading container logs.

Both stages share one log, so the stream is a single ordered record rather
than two feeds to interleave. A write failure here is swallowed: `record()`
runs *after* the send, so letting an audit-log failure propagate would turn
a delivered message into a crashed poll cycle.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `TOCSIN_MODE` | `offgrid` | Gates the MQTT fallback leg (design doc §8) -- `hybrid` required for it to ever fire. Also reported on this service's liveness heartbeat (`tocsin:status:dispatcher`), alongside whether stage 2 is enabled. |
| `TOCSIN_DATA_DIR` | repo-root `data/` | Directory containing `fips.csv`. |
| `DISPATCHER_REDIS_URL` | `redis://redis:6379/0` | Redis connection URL (stream consumption, idempotency keys, circuit breaker state). |
| `DISPATCHER_CONSUMER_NAME` | `dispatcher` | Redis consumer-group consumer name. Fixed, not hostname-derived -- see `__init__.py`'s comment (same reasoning as `fusion`'s). |
| `MESHTASTIC_SERIAL_DEV_PATH` | *(unset -- autodetect)* | Serial device path, e.g. `/dev/ttyUSB0`. Only needed if more than one serial device is attached to the host. |
| `MESHTASTIC_GATEWAY_NODE_ID` | *(unset -- MQTT fallback disabled)* | Decimal node ID of the Meshtastic node that will relay MQTT-injected messages onto the mesh. |
| `MQTT_HOST` / `MQTT_PORT` | `mosquitto` / `1883` | The local MQTT broker (`compose.yaml`'s `mosquitto` service). |
| `MESHTASTIC_MQTT_REGION` | `US` | Region segment of the `msh/{region}/2/json/mqtt/` topic -- must match the gateway node's configured region. |
| `DISPATCHER_LITELLM_BASE_URL` | *(unset -- stage 2 disabled)* | Base URL for a LiteLLM proxy or any OpenAI-compatible `/chat/completions` endpoint. Required for stage 2 to run at all. |
| `DISPATCHER_LITELLM_API_KEY` | *(none)* | Sent as `Authorization: Bearer <key>` if set. |
| `DISPATCHER_LITELLM_MODEL` | `gpt-4o-mini` | Model name passed to the chat-completions request. |
| `DISPATCHER_CIRCUIT_BREAKER_THRESHOLD` | `5` | Consecutive LiteLLM failures before the breaker opens. |
| `DISPATCHER_CIRCUIT_BREAKER_COOLDOWN_SECONDS` | `300` | How long the breaker stays open before allowing another attempt. |

## Development

```sh
uv sync
uv run pytest
```
