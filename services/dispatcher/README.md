# dispatcher

Consumes canonical Alerts from `fusion`'s `tocsin:alerts` Redis Stream and
dispatches a deterministic, zero-dependency stage-1 message the moment a
Tier A SAME header decodes (design doc §7, §10 milestone 6). Also
consumes guarded transcripts from `stt_worker`'s `tocsin:transcripts`
stream and, when LiteLLM is configured, enriches Tier A alerts with a
compressed impact clause as a second, later message (stage 2, milestone
7). Both stages send over the same Meshtastic egress: serial or TCP,
`wantAck`.

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
`meshtastic` PyPI package's node interfaces (`meshtastic_node.py` --
serial and TCP behind one client, verified against the library's actual
installed source for `sendText`'s `onResponse` callback shape and both
constructor signatures, not guessed), and `dispatch.py`'s `MeshSender`
wrapping it: ack within 15s -> delivered, otherwise not.

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
- Tier B/C alerts are logged as skipped, not queued for any other egress.
- A transient failure right at the send step (a serial/TCP exception)
  still means that exact message won't be retried until its 24h
  idempotency claim expires -- there's no fallback beyond the node itself.
- Not verified against a real Meshtastic node, a real LiteLLM/OpenAI-compatible
  endpoint, or real Redis -- verified against fixtures and fakes only (none
  of that infrastructure exists in this authoring sandbox).

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
| `TOCSIN_MODE` | `offgrid` | Reported on this service's liveness heartbeat (`tocsin:status:dispatcher`), alongside whether stage 2 is enabled. |
| `TOCSIN_DATA_DIR` | repo-root `data/` | Directory containing `fips.csv`. |
| `DISPATCHER_REDIS_URL` | `redis://redis:6379/0` | Redis connection URL (stream consumption, idempotency keys, circuit breaker state). |
| `DISPATCHER_CONSUMER_NAME` | `dispatcher` | Redis consumer-group consumer name. Fixed, not hostname-derived -- see `__init__.py`'s comment (same reasoning as `fusion`'s). |
| `MESHTASTIC_ENABLED` | `true` (unset), `false` via `compose.yaml` | `false` runs with no Meshtastic node attached -- see "Running without a mesh node" below. Also reported on the liveness heartbeat as `mesh`. |
| `MESHTASTIC_TRANSPORT` | `serial` | `serial` (USB) or `tcp` (node on the network) -- see "Reaching the node over the network". Anything else is a startup error. |
| `MESHTASTIC_SERIAL_DEV_PATH` | *(unset -- autodetect)* | Serial device path, e.g. `/dev/ttyUSB0`. Only needed if more than one serial device is attached to the host. Ignored when transport is `tcp`. |
| `MESHTASTIC_TCP_HOST` | *(unset)* | Hostname/IP of the node. Required when transport is `tcp`; missing is a startup error, not a silent fall back to serial. |
| `MESHTASTIC_TCP_PORT` | `4403` | Meshtastic's default network API port. |
| `MESHTASTIC_CHANNEL_INDEX` | *(unset -- node's Primary channel)* | Channel index (0-7) to send on. |
| `DISPATCHER_LITELLM_BASE_URL` | *(unset -- stage 2 disabled)* | Base URL for a LiteLLM proxy or any OpenAI-compatible `/chat/completions` endpoint. Required for stage 2 to run at all. |
| `DISPATCHER_LITELLM_API_KEY` | *(none)* | Sent as `Authorization: Bearer <key>` if set. |
| `DISPATCHER_LITELLM_MODEL` | `gpt-4o-mini` | Model name passed to the chat-completions request. |
| `DISPATCHER_CIRCUIT_BREAKER_THRESHOLD` | `5` | Consecutive LiteLLM failures before the breaker opens. |
| `DISPATCHER_CIRCUIT_BREAKER_COOLDOWN_SECONDS` | `300` | How long the breaker stays open before allowing another attempt. |

## Reaching the node over the network

Design doc §7's flow is `sendText(wantAck=True)` **over serial/TCP**, so the node
does not have to be on a USB cable. A node reachable over WiFi/Ethernet works
the same way, with the same 15s ack wait.

In `.env`:

```sh
COMPOSE_FILE=compose.yaml          # no USB device to map, so skip the overlay
MESHTASTIC_ENABLED=true            # the overlay would normally set this
MESHTASTIC_TRANSPORT=tcp
MESHTASTIC_TCP_HOST=192.168.1.50   # hostname or IP of the node
MESHTASTIC_TCP_PORT=4403           # optional; 4403 is the Meshtastic default
```

`MESHTASTIC_ENABLED=true` is explicit here because `compose.mesh.yaml` -- the
overlay that normally turns transmit on -- exists only to map a USB device, and
a networked node has none to map. Adding it would demand a `/dev` path that
isn't there.

This is a LAN link, not an internet one, so it stays valid under
`TOCSIN_MODE=offgrid`.

Two operational notes. The node's network API must be enabled and reachable from
inside the container -- Docker's default bridge network can reach LAN addresses,
but a node on a different VLAN or behind a host firewall may not be. And the
interface is opened once at startup and never re-dialed in-process, so if the
node reboots or the LAN drops, dispatcher exits 1 and `restart: on-failure`
reconnects it; that is the reconnect mechanism, deliberately, rather than
in-process retry logic that could mask a genuinely dead link.

The dispatch log names whichever transport actually carried the message
(`tcp` / `tcp_no_ack` rather than `serial` / `serial_no_ack`), so `GET
/dispatches` and the web UI show the real path.

## Running without a mesh node

Not everyone wants the radio. Tocsin's whole receive side -- SAME decode,
segment capture, transcription, the alert log and the web UI -- is independent
of Meshtastic, so a monitoring-only station is a supported configuration.

In `.env`, drop the mesh overlay from `COMPOSE_FILE`:

```sh
COMPOSE_FILE=compose.yaml
```

That single change both removes the `devices:` mapping and defaults
`MESHTASTIC_ENABLED` to `false`. It has to be a file rather than a flag:
Docker refuses to *start* a container whose `devices:` host path is missing,
so with the mapping in the base file an absent node kills the container before
its entrypoint runs, and a list entry in an override cannot be unset once the
base declares it.

Stage 1 still runs in full -- dedup, idempotency, rate limiting, message
building -- and the dispatch log records every message with reason
`mesh_disabled`, so `GET /dispatches` and the web UI show exactly what would
have gone out over the mesh. Only the transmit is skipped.

With the mesh *enabled*, a node that won't open is still a loud exit 1 under
`restart: on-failure` -- someone who configured a radio and lost it should find
out immediately, not run a silently muted station.

## Development

```sh
uv sync
uv run pytest
```
