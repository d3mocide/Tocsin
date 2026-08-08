# same-decoder

Subscribes to `sdr-rx`'s `same.<site>.<channel>` ZMQ topic (22050 Hz s16le
mono), pipes each channel's audio to its own `multimon-ng -t raw -a EAS -`
subprocess, parses decoded `ZCZC` SAME headers, tags them with a tier from
`data/same_event_codes.yaml`, and logs one structured JSON line per event.

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

Structured events currently go to stdout as JSON (`LoggingEventSink`) --
there's no Redis Streams / fusion consumer yet (that's Phase 5); `EventSink`
is the seam a real publisher drops into later.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `SAME_DECODER_ZMQ_CONNECT` | `tcp://sdr-rx:5555` | Address to connect to sdr-rx's ZMQ PUB socket. |
| `TOCSIN_DATA_DIR` | repo-root `data/` | Directory containing `same_event_codes.yaml`. Set by compose to the mounted `data/` volume in containers. |

## Development

```sh
uv sync
uv run pytest
```
