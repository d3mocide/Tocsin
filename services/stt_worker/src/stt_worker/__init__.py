"""stt-worker entrypoint: subscribe to segment_capture's `capture.*`
topic, trim each WAV to its voice-only portion, transcribe with
whisper.cpp, and apply hallucination guards before logging a transcript
(design doc §6).

Requires `whisper-cli` on PATH (built from source in the Dockerfile -- no
apt package exists for a Debian stable base as of this writing, see the
Dockerfile's comment) and a real ggml model file mounted at
STT_WORKER_MODEL_PATH. Neither is available in this authoring sandbox, so
this entrypoint itself isn't exercised end to end here -- every stage
upstream of the real whisper-cli binary (the subscriber, WAV trimming,
guard logic, transcript JSON parsing, and service wiring) is unit tested
instead.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import remote_http, whispercpp
from .service import DEFAULT_REMOTE_BUDGET_SECONDS, TranscriptionWorker
from .subscriber import CaptureSubscriber

DEFAULT_ZMQ_CONNECT = "tcp://segment-capture:5556"
DEFAULT_WORK_DIR = Path("/tmp/stt_worker")


def _build_sink():
    """`None` falls back to `TranscriptionWorker`'s own default
    (`LoggingTranscriptSink`) -- same seam pattern as
    `same_decoder._build_sink`/`nws_poller._build_sink`."""
    redis_url = os.environ.get("STT_WORKER_REDIS_URL")
    if not redis_url:
        return None
    import redis as redis_lib

    from .redis_sink import RedisStreamTranscriptSink

    return RedisStreamTranscriptSink(redis_lib.from_url(redis_url))


def _build_remote_run():
    """`STT_CHAIN` (design doc §6): `local` (default, offgrid) disables
    remote entirely; `local,remote` (hybrid) enables it, but only if a
    base URL is actually configured -- a hybrid-only misconfiguration must
    never block the local-only path that works off-grid too (CLAUDE.md's
    connectivity rule), so this warns and falls back rather than
    exiting."""
    chain = {part.strip() for part in os.environ.get("STT_CHAIN", "local").split(",") if part.strip()}
    if "remote" not in chain:
        return None
    base_url = os.environ.get("STT_WORKER_REMOTE_BASE_URL")
    if not base_url:
        print(
            "stt-worker: STT_CHAIN includes 'remote' but STT_WORKER_REMOTE_BASE_URL is unset -- "
            "continuing local-only.",
            file=sys.stderr,
        )
        return None
    api_key = os.environ.get("STT_WORKER_REMOTE_API_KEY") or None
    model = os.environ.get("STT_WORKER_REMOTE_MODEL", remote_http.DEFAULT_MODEL)

    def remote_run(wav_path):
        return remote_http.run(wav_path, base_url=base_url, api_key=api_key, model=model)

    return remote_run


def main() -> None:
    connect_addr = os.environ.get("STT_WORKER_ZMQ_CONNECT", DEFAULT_ZMQ_CONNECT)
    model_path = os.environ.get("STT_WORKER_MODEL_PATH")

    # Off-grid means pre-staged, never download-on-first-boot (design doc
    # §8) -- discovering a missing model mid-event is the scenario this
    # startup assertion guards against, not something to fail into later.
    if not model_path or not Path(model_path).is_file():
        print(
            f"stt-worker: no model file at STT_WORKER_MODEL_PATH={model_path!r}. "
            "Run `make fetch-models` while network is still available -- see "
            "services/stt_worker/README.md.",
            file=sys.stderr,
        )
        sys.exit(1)

    work_dir = Path(os.environ.get("STT_WORKER_WORK_DIR", str(DEFAULT_WORK_DIR)))
    language = os.environ.get("STT_WORKER_LANGUAGE", whispercpp.DEFAULT_LANGUAGE)
    initial_prompt = os.environ.get("STT_WORKER_INITIAL_PROMPT") or None
    binary = os.environ.get("STT_WORKER_WHISPER_BINARY", whispercpp.DEFAULT_BINARY)
    remote_budget_seconds = float(
        os.environ.get("STT_WORKER_REMOTE_BUDGET_SECONDS", DEFAULT_REMOTE_BUDGET_SECONDS)
    )

    subscriber = CaptureSubscriber(connect_addr)
    worker = TranscriptionWorker(
        model_path,
        work_dir,
        sink=_build_sink(),
        binary=binary,
        language=language,
        initial_prompt=initial_prompt,
        remote_run=_build_remote_run(),
        remote_budget_seconds=remote_budget_seconds,
    )
    print(f"stt-worker: subscribed to {connect_addr}, model={model_path}", flush=True)
    try:
        while True:
            payload = subscriber.recv(timeout_ms=1000)
            if payload is None:
                continue
            worker.handle_capture(payload)
    except KeyboardInterrupt:
        pass
    finally:
        subscriber.close()
