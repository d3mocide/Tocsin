# stt-worker

Subscribes to `segment_capture`'s `capture.<site>.<channel>` topic, trims
each WAV to its voice-only portion, transcribes it with whisper.cpp, and
guards against hallucinated output before logging a transcript (milestone
4, `docs/design/master-prompt.md` §10, §6).

## Design

Two providers now (Phase 7 added the second): `local_whispercpp`
(`whispercpp.py`) and `remote_http` (`remote_http.py`, an OpenAI-compatible
`/v1/audio/transcriptions` endpoint -- design doc §6's own reasoning:
"that one remote endpoint shape covers a self-hosted faster-whisper-server,
LiteLLM routing, or a commercial API with no code change between them").
Still no formal `Provider` interface class -- this codebase's established
idiom for pluggability is an injected callable (`whisper_run`,
`remote_run`), not a class hierarchy, so a third provider would follow the
same shape rather than triggering a bigger abstraction. Both share
provider-agnostic `Transcript`/`Segment` value types (`transcript.py`,
extracted from `whispercpp.py` now that there's a second real thing to
share them with, per CLAUDE.md's own stated exception to "stay concrete").
`local_faster_whisper` (CUDA/Jetson) still isn't implemented.

`STT_CHAIN` (design doc §6, "race, don't chain"): `local` (default,
offgrid) never touches the network; `local,remote` (hybrid) races both
concurrently on Tier A captures only (Tier B stays local-only). Local is
always waited for in full -- "the floor... always completes" -- remote
gets a bounded budget from the start of the race
(`STT_WORKER_REMOTE_BUDGET_SECONDS`); if it returns usable text within
that budget, it wins, otherwise local's result is used. "Remote wins... with
a better score" (design doc's exact wording) simplifies to "wins with
non-empty text" here -- see `service.py`'s `TranscriptionWorker`
docstring for why a real cross-provider confidence comparison isn't
implementable against a generic OpenAI-compatible endpoint (its standard
response is just `{"text": ...}`, with none of whisper.cpp's
`no_speech_prob`/`avg_logprob` guaranteed).

`STT_CHAIN=remote` (no `local`) is the third form: a hybrid deployment that
transcribes entirely against the remote endpoint and stages no ggml model
at all. `STT_WORKER_MODEL_PATH` is then unused and nothing waits for a
model file -- waiting for one that was never going to arrive is what left
`stt-worker` showing "no heartbeat" on the status board with no
transcripts ever produced. Every tier goes remote in this mode (Tier B's
local-only rule is about preferring the free local provider, and there
isn't one). This form is hybrid-only by construction: it makes
transcription depend on the network, so an `offgrid` deployment must
always keep `local` in the chain.

Transcripts publish to Redis Streams (`redis_sink.py`, stream
`tocsin:transcripts`) when `STT_WORKER_REDIS_URL` is set -- `dispatcher`'s
stage 2 (Phase 7) consumes from there via a consumer group. Without that
env var (local/test runs), transcripts fall back to stdout as JSON
(`LoggingTranscriptSink`).

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

### Live transcription and keyword-triggered alerts addendum

`handle_capture` branches on the incoming payload's `capture_kind`
(`segment_capture.bus`'s discriminator). A `"live"` capture -- continuous,
VAD-cut, from `segment_capture`'s `LIVE_TRANSCRIPTION_ENABLED` path, no
SAME header involved -- always transcribes local-only, never races
remote, and is dropped outright (not sent over the network) if no local
provider is configured at all: continuous transcription has to work fully
offgrid, same as everything else this document calls core. Its guarded
transcript is recorded with `event_code=LIVE`/`tier=C`
(`LIVE_EVENT_CODE`/`LIVE_TIER`) rather than nulls, which is also what
keeps it out of `dispatcher`'s stage 2 with no changes needed there --
Tier C already fails that gate.

A `"live"` transcript that passes the hallucination guard is then scanned
by `keyword_match.KeywordMatcher` (loads `data/keyword_triggers.yaml` +
`data/same_event_codes.yaml`, same per-service loader pattern as every
other `TierTable`) for a spoken hazard phrase. A match publishes a
`KeywordEvent` to `tocsin:keyword_events` (`redis_sink.py`), which
`fusion` turns into a `TRANSCRIPT_ONLY` alert -- see
`docs/design/master-prompt.md`'s live-transcription addendum to §4/§6/§7
and `services/fusion/README.md`.

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
(`whispercpp.py`), the `remote_http` provider (`remote_http.py`), the
`STT_CHAIN` race logic (`service.py`'s `TranscriptionWorker._transcribe`
-- tests cover remote winning in-budget, local winning on a remote
timeout/error/empty-text, Tier B never racing, and that a slow/hanging
remote thread doesn't block the caller past its budget), the hallucination
guard (`guard.py`), and the Redis Streams sink (`redis_sink.py`).

The remote upload's Content-Type is derived via `mimetypes.guess_type`
rather than a hardcoded string (`.wav` -> `audio/x-wav`) -- see
`remote_http.py`'s docstring. A literal `"audio/wav"` once made every
remote call fail against a real self-hosted backend that didn't recognize
that exact string and silently mis-detected the upload as mp3.

A remote timeout or error always falls back to the local result silently
*to the pipeline* (availability over quality, per design doc §6) but is
still logged to stderr as `stt-worker: remote STT failed, using local
result instead: ...` -- `docker compose logs stt-worker` is enough to
notice a remote endpoint that's failing on every capture, without having
to go find that endpoint's own dashboard.
whisper.cpp itself, a real ggml model, and a real remote endpoint aren't
available in this authoring sandbox, so neither provider's real wire
behavior (as opposed to the researched/documented shape) is verified end
to end here -- see `docs/design/tracking.md`.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `STT_WORKER_ZMQ_CONNECT` | `tcp://sdr-rx:5556` | Address to connect to segment-capture's capture-ready ZMQ PUB socket. `sdr-rx`'s hostname, not `segment-capture`'s -- segment_capture ships inside sdr-rx's container now (see `services/sdr_rx/README.md`'s "Container" section) and no longer has a container/hostname of its own, though it still binds the same port there. |
| `STT_WORKER_MODEL_PATH` | *(required unless `STT_CHAIN=remote`)* | Path to a ggml model file (see `make fetch-models`). Ignored entirely when the chain has no `local`. Otherwise: unset is a misconfiguration and exits 1; set-but-not-yet-present makes the worker log once and wait, polling every 15s, so a model dropped into `./models/` later starts it with no restart needed. Never downloaded on first boot -- off-grid means pre-staged (design doc §8). |
| `STT_WORKER_WORK_DIR` | `/tmp/stt_worker` | Scratch directory for trimmed WAV copies. |
| `STT_WORKER_LANGUAGE` | `en` | Passed to whisper-cli's `-l`. |
| `STT_WORKER_INITIAL_PROMPT` | *(none)* | Passed to whisper-cli's `--prompt` -- design doc §6 recommends seeding local county/place names, since NWR's synthesized voices fail almost exclusively on proper nouns. |
| `STT_WORKER_WHISPER_BINARY` | `whisper-cli` | Binary name/path, in case the Dockerfile's build ever needs to change it. |
| `STT_WORKER_REDIS_URL` | *(unset -- logs to stdout)* | Redis connection URL. When set, transcripts publish to the `tocsin:transcripts` stream for `dispatcher` instead of stdout. |
| `STT_CHAIN` | `local` | `local`, `local,remote`, or `remote` -- see "Design" above. |
| `STT_WORKER_REMOTE_BASE_URL` | *(unset)* | Base URL for the `remote_http` provider. Required for `STT_CHAIN=local,remote` to actually enable remote (otherwise falls back to local-only with a warning). With `STT_CHAIN=remote` there is nothing to fall back to, so an unset URL exits 1. |
| `STT_WORKER_REMOTE_API_KEY` | *(none)* | Sent as `Authorization: Bearer <key>` if set. |
| `STT_WORKER_REMOTE_MODEL` | `whisper-1` | Passed as the `model` form field. |
| `STT_WORKER_REMOTE_BUDGET_SECONDS` | `10` | How long remote gets to win the race, measured from when both providers start. |
| `LIVE_TRANSCRIPTION_ALLOW_REMOTE` | `false` | When `STT_CHAIN=remote` (no local model staged), setting `true` allows ambient live audio chunks to be transcribed via the remote endpoint. |
| `TOCSIN_DATA_DIR` | *(unset -- inferred, fails inside a container)* | Directory containing `keyword_triggers.yaml`/`same_event_codes.yaml` for keyword matching. Must be set in Docker (see "Live transcription addendum" above); a missing/unloadable table degrades to no keyword detection rather than refusing to start. |

## Development

```sh
uv sync
uv run pytest
```
