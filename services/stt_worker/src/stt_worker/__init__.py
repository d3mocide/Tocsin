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
import time
from pathlib import Path

from . import heartbeat as heartbeat_module, remote_http, whispercpp
from .service import DEFAULT_REMOTE_BUDGET_SECONDS, TranscriptionWorker
from .subscriber import CaptureSubscriber

DEFAULT_ZMQ_CONNECT = "tcp://sdr-rx:5556"
DEFAULT_WORK_DIR = Path("/tmp/stt_worker")
MODEL_POLL_INTERVAL_SECONDS = 15.0
MODEL_REMINDER_INTERVAL_SECONDS = 300.0


def _build_redis_client():
    """Built once in `main()` and shared by the transcript sink and the
    liveness heartbeat rather than each opening its own connection."""
    redis_url = os.environ.get("STT_WORKER_REDIS_URL")
    if not redis_url:
        return None
    import redis as redis_lib

    return redis_lib.from_url(redis_url)


def _build_sink(redis_client):
    """`None` falls back to `TranscriptionWorker`'s own default
    (`LoggingTranscriptSink`) -- same seam pattern as
    `same_decoder._build_sink`/`nws_poller._build_sink`."""
    if redis_client is None:
        return None
    from .redis_sink import RedisStreamTranscriptSink

    return RedisStreamTranscriptSink(redis_client)


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


def await_model(
    model_path: str,
    *,
    poll_interval_seconds: float = MODEL_POLL_INTERVAL_SECONDS,
    reminder_interval_seconds: float = MODEL_REMINDER_INTERVAL_SECONDS,
    sleep=time.sleep,
    clock=time.monotonic,
) -> None:
    """Blocks until the model file exists, rather than exiting 1 and leaving
    `restart: on-failure` to retry.

    The recovery is identical either way -- a model dropped into `./models/`
    is picked up with no manual intervention -- but the restart loop
    reprinted this same line every couple of seconds, interleaved into
    `docker compose logs` with every other service's output, which is how a
    single missing file came to look like the stack was broken. Waiting
    keeps one process idle and quiet instead. Still says so periodically:
    silence would make a misconfigured worker indistinguishable from a
    working one on a night with no captures."""
    if Path(model_path).is_file():
        return
    print(
        f"stt-worker: no model file at STT_WORKER_MODEL_PATH={model_path!r} -- waiting for one. "
        "Run `make fetch-models` while network is still available (it lands in ./models/, "
        "bind-mounted here); see services/stt_worker/README.md.",
        file=sys.stderr,
        flush=True,
    )
    last_reminder = clock()
    while not Path(model_path).is_file():
        sleep(poll_interval_seconds)
        if clock() - last_reminder >= reminder_interval_seconds:
            print(f"stt-worker: still waiting for a model file at {model_path!r}.", file=sys.stderr, flush=True)
            last_reminder = clock()
    print(f"stt-worker: model file {model_path!r} appeared -- starting.", file=sys.stderr, flush=True)


def main() -> None:
    connect_addr = os.environ.get("STT_WORKER_ZMQ_CONNECT", DEFAULT_ZMQ_CONNECT)
    model_path = os.environ.get("STT_WORKER_MODEL_PATH")

    # Off-grid means pre-staged, never download-on-first-boot (design doc
    # §8), so an unset path is a misconfiguration with nothing to wait for.
    # A *set* path that isn't there yet is the recoverable case -- see
    # `await_model`.
    if not model_path:
        print("stt-worker: STT_WORKER_MODEL_PATH is required -- refusing to start", file=sys.stderr)
        sys.exit(1)
    await_model(model_path)

    work_dir = Path(os.environ.get("STT_WORKER_WORK_DIR", str(DEFAULT_WORK_DIR)))
    language = os.environ.get("STT_WORKER_LANGUAGE", whispercpp.DEFAULT_LANGUAGE)
    initial_prompt = os.environ.get("STT_WORKER_INITIAL_PROMPT") or None
    binary = os.environ.get("STT_WORKER_WHISPER_BINARY", whispercpp.DEFAULT_BINARY)
    remote_budget_seconds = float(
        os.environ.get("STT_WORKER_REMOTE_BUDGET_SECONDS", DEFAULT_REMOTE_BUDGET_SECONDS)
    )

    redis_client = _build_redis_client()
    subscriber = CaptureSubscriber(connect_addr)
    worker = TranscriptionWorker(
        model_path,
        work_dir,
        sink=_build_sink(redis_client),
        binary=binary,
        language=language,
        initial_prompt=initial_prompt,
        remote_run=_build_remote_run(),
        remote_budget_seconds=remote_budget_seconds,
    )
    heartbeat = heartbeat_module.build(redis_client)
    print(f"stt-worker: subscribed to {connect_addr}, model={model_path}", flush=True)
    try:
        while True:
            if heartbeat is not None:
                heartbeat.beat(model=Path(model_path).name, chain=os.environ.get("STT_CHAIN", "local"))
            payload = subscriber.recv(timeout_ms=1000)
            if payload is None:
                continue
            worker.handle_capture(payload)
    except KeyboardInterrupt:
        pass
    finally:
        subscriber.close()
