# same-decoder

Subscribes to `sdr-rx`'s `same.<site>.<channel>` ZMQ topic (22050 Hz s16le
mono), pipes each channel's audio to its own `multimon-ng -t raw -a EAS -`
subprocess, parses decoded `ZCZC` SAME headers, tags them with a tier from
`data/same_event_codes.yaml`, and logs one structured JSON line per event.

No `compose.yaml` service or Dockerfile of its own: this project ships
inside `sdr-rx`'s container image (`../sdr_rx/Dockerfile`, build context
the repo root) as one of four independent uv projects/venvs, started by
`../sdr_rx/entrypoint.sh` as a self-restarting background process. Still
fully independent of `sdr-rx` at the Python level (own `pyproject.toml`,
own tests, no cross-import) -- `../sdr_rx/README.md`'s "Container" section
has the full picture.

## Status

Implemented and unit tested: header parsing (`parser.py`), tier lookup
(`tiers.py`), dedup of the SAME header's repeated transmissions
(`dedup.py`), the multimon-ng subprocess wrapper (`multimon.py`), the ZMQ
subscriber (`subscriber.py`), and the pipeline wiring them together
(`service.py`). multimon-ng itself isn't installed in the authoring
sandbox, so `multimon.py` and `service.py` are tested against a small
stand-in script rather than the real binary -- see their test files.

**Not yet verified:** against real multimon-ng output or a recorded RWT/RMT
capture (roadmap Phase 2 exit criteria). The header-parsing regex is
checked against real-format example strings, and the "multimon-ng emits a
decoded line only once two of three copies agree" assumption in
`parser.py`'s docstring is taken from the design doc, not confirmed against
multimon-ng's actual source -- worth an early check once real audio is
flowing (see the repo root README's bring-up runbook).

Structured events go to Redis Streams (`redis_sink.py`, stream
`tocsin:same_events`) when `SAME_DECODER_REDIS_URL` is set -- `fusion`
(Phase 5) consumes from there via a consumer group so a crash mid-event
resumes rather than loses it (design doc §5). Without that env var (local/
test runs), events fall back to stdout as JSON (`LoggingEventSink`).
`EventSink` is the seam either implementation drops into.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `SAME_DECODER_ZMQ_CONNECT` | `tcp://localhost:5555` | Address to connect to sdr-rx's ZMQ PUB socket -- `localhost`, since both run in the same container now (see above). |
| `TOCSIN_DATA_DIR` | repo-root `data/` | Directory containing `same_event_codes.yaml`. Set by compose to the mounted `data/` volume in containers. |
| `SAME_DECODER_REDIS_URL` | *(unset -- logs to stdout)* | Redis connection URL. When set, events publish to the `tocsin:same_events` stream for `fusion` instead of stdout. |

## Development

```sh
uv sync
uv run pytest
```
