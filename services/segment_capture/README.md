# segment-capture

Captures a full SAME voice-message clip -- header through EOM -- from
`sdr-rx`'s ring buffer, and hands it off to `stt-worker` (milestone 4,
`docs/design/master-prompt.md` §10, §4).

No `compose.yaml` service or Dockerfile of its own: this project ships
inside `sdr-rx`'s container image (`../sdr_rx/Dockerfile`, build context
the repo root) as one of four independent uv projects/venvs, started by
`../sdr_rx/entrypoint.sh` as a self-restarting background process. Still
fully independent of `sdr-rx` at the Python level (own `pyproject.toml`,
own tests, no cross-import) -- `../sdr_rx/README.md`'s "Container" section
has the full picture. `stt-worker` stays a separate container and reaches
this process's own ZMQ PUB socket (below) via `sdr-rx`'s hostname, not
`segment-capture`'s -- see `services/stt_worker/README.md`.

## Design

Runs its own multimon-ng (`-a EAS`) against the same `same.<site>.<channel>`
22050 Hz feed `same-decoder` subscribes to, independently of it -- both
are siblings of `sdr-rx` in the architecture diagram (§2), not chained
through one another, so either can be restarted without the other. On a
`ZCZC` line, it starts a capture; on `NNNN` (or a 300s hard timeout), it
finalizes one.

The actual audio always comes from `sdr-rx`'s tmpfs ring buffer, not the
live ZMQ stream: multimon-ng's decode only reports a message a few seconds
after it actually started (the header repeats three times), so reading the
ring buffer's already-buffered last few seconds ("pre-roll") is what
captures the SAME header audio itself rather than starting mid-header. The
ring buffer only holds a rolling 30s window, but a capture can run up to
300s, so once started, `segment_capture` polls the ring buffer faster than
its wraparound to drain new audio for the rest of the message.

On finalize, it detects where the 8-11s, 1050 Hz attention tone ends and
voice begins (`tone.py`) -- SAME's own AFSK header tones and NWR voice
audio are both far from 1050 Hz, so a long contiguous run of energy
dominated by that one frequency is unambiguous. It writes the **full**
segment (header, tone, and voice) as a 16 kHz mono s16le WAV -- already
`stt_worker`'s uniform input contract (§6) -- plus that voice-start offset
as metadata; trimming before inference is `stt_worker`'s job, not this
service's (§6's first preprocessing step).

## Status

Implemented and unit tested: boundary line detection (`boundary.py`), the
multimon-ng subprocess wrapper (`multimon.py`, identical in shape to
`same_decoder`'s own -- duplicated rather than shared, see CLAUDE.md), the
ZMQ subscriber (`subscriber.py`), the ring-buffer reader's pre-roll/
live-drain/overrun logic (`ring_reader.py`), the 1050 Hz tone-boundary
detector against synthetic tone+noise signals (`tone.py`), the WAV writer
(`writer.py`), the capture-ready ZMQ publisher (`bus.py`), and the service
wiring (`service.py`). multimon-ng, a real `sdr-rx` ring buffer, and a
shared volume between the two containers aren't available in this
authoring sandbox, so the full path isn't exercised end to end here -- see
`docs/design/tracking.md`.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `SEGMENT_CAPTURE_ZMQ_CONNECT` | `tcp://localhost:5555` | Address to connect to sdr-rx's ZMQ PUB socket (the `same.*` topic) -- `localhost`, since both run in the same container now (see above). |
| `SEGMENT_CAPTURE_ZMQ_BIND` | `tcp://0.0.0.0:5556` | Bind address for this service's own capture-ready ZMQ PUB socket. Reachable from other containers (`stt-worker`) at `sdr-rx`'s hostname, since this process no longer has one of its own. |
| `SEGMENT_CAPTURE_RING_BUFFER_DIR` | `/run/sdr_rx_ring` | Must be the same directory sdr-rx writes its ring buffer to. A private `tmpfs:` mount on the shared container now, not a named volume across two containers the way it was before this merge. |
| `SEGMENT_CAPTURE_OUTPUT_DIR` | `/var/lib/segment_capture/captures` | Where finished WAV files are written -- a volume shared with stt-worker. |
| `SEGMENT_CAPTURE_PREROLL_SECONDS` | `10` | How much already-buffered ring-buffer audio to grab when a message starts. |
| `SEGMENT_CAPTURE_HARD_TIMEOUT_SECONDS` | `300` | Force-finalize a capture that never sees an EOM (design doc §4). |

## Development

```sh
uv sync
uv run pytest
```
