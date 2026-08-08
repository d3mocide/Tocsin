# stt-worker

Subscribes to `segment_capture`'s `capture.<site>.<channel>` topic, trims
each WAV to its voice-only portion, transcribes it with whisper.cpp, and
guards against hallucinated output before logging a transcript (milestone
4, `docs/design/master-prompt.md` §10, §6).

## Design

Implements exactly one provider, `local_whispercpp` -- design doc §6 also
names `local_faster_whisper` (CUDA/Jetson) and `remote_http`
(OpenAI-compatible endpoint), but per CLAUDE.md, a pluggable provider
interface isn't built until there's a second real provider to generalize
from. `whispercpp.py` is a plain module, not an abstraction.

Two of the design doc's preprocessing steps live here:

1. **Trim before inference** (`trim.py`): cuts the WAV at the
   `voice_start_sample` offset `segment_capture` computed (its `tone.py`
   locates where the 1050 Hz attention tone ends), stripping the SAME
   header and tone before whisper.cpp ever sees them.
2. **Hallucination guards** (`guard.py`): `no_speech_prob`/`avg_logprob`
   thresholds plus a blocklist for classic Whisper artifacts ("Thank you
   for watching," subtitle credit strings). An unguarded transcript
   feeding a mesh broadcast is called out in the design doc as the worst
   failure chain in this system -- treated as a correctness requirement,
   not a polish item.

**A real caveat, found via research rather than assumed:** whisper.cpp's
CLI JSON output (`-oj -ojf`) only gained per-segment `no_speech_prob` in a
2026 upstream PR (`ggml-org/whisper.cpp#2654`), and `avg_logprob` doesn't
appear to be exposed through the CLI's JSON output at all as of this
writing, despite existing internally in the decoder. `guard.py` checks
each threshold only when whisper.cpp actually supplies that field for a
segment, so the guard still functions (via the blocklist, unconditionally)
regardless of exactly which whisper.cpp build produced the transcript --
see `whispercpp.py`'s docstring.

## Status

Implemented and unit tested: the ZMQ subscriber (`subscriber.py`), WAV
trimming (`trim.py`), the whisper-cli subprocess wrapper and JSON parsing
(`whispercpp.py`), the hallucination guard (`guard.py`), and the service
wiring (`service.py`). whisper.cpp itself and a real ggml model aren't
available in this authoring sandbox, so the real binary's actual JSON
output shape (as opposed to the researched/documented shape) isn't
verified end to end here -- see `docs/design/tracking.md`.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `STT_WORKER_ZMQ_CONNECT` | `tcp://segment-capture:5556` | Address to connect to segment-capture's capture-ready ZMQ PUB socket. |
| `STT_WORKER_MODEL_PATH` | *(required)* | Path to a ggml model file (see `make fetch-models`). Startup fails loudly if missing or not a file -- off-grid means pre-staged, never downloaded on first boot (design doc §8). |
| `STT_WORKER_WORK_DIR` | `/tmp/stt_worker` | Scratch directory for trimmed WAV copies. |
| `STT_WORKER_LANGUAGE` | `en` | Passed to whisper-cli's `-l`. |
| `STT_WORKER_INITIAL_PROMPT` | *(none)* | Passed to whisper-cli's `--prompt` -- design doc §6 recommends seeding local county/place names, since NWR's synthesized voices fail almost exclusively on proper nouns. |
| `STT_WORKER_WHISPER_BINARY` | `whisper-cli` | Binary name/path, in case the Dockerfile's build ever needs to change it. |

## Development

```sh
uv sync
uv run pytest
```
