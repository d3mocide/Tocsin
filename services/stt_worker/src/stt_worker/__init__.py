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


def _build_keyword_sink(redis_client):
    if redis_client is None:
        return None
    from .redis_sink import RedisStreamKeywordEventSink

    return RedisStreamKeywordEventSink(redis_client)


def _build_keyword_matcher():
    """Loaded unconditionally, not gated by an env var of its own --
    it's only ever consulted for `capture_kind == "live"` captures
    (`service.py`), which segment_capture's own `LIVE_TRANSCRIPTION_ENABLED`
    already gates, so there's no separate flag to keep in sync here. A
    missing/malformed table degrades to "no keyword detection" rather than
    refusing to start -- unlike the SAME event-code table every capture
    needs for tiering, this is a supplementary detection path, not a core
    one (CLAUDE.md's connectivity rule doesn't apply -- this stays fully
    local either way).

    Catches `RuntimeError` too, not just `OSError`: an unset
    `TOCSIN_DATA_DIR` inside a Docker image makes `_default_data_dir()`
    raise `RuntimeError` rather than fail to find a file (see its
    docstring/test) -- same class of bug as the one `tiers.py` across
    every other service already guards against (docs/design/tracking.md,
    2026-08-08), just reachable from a different loader here."""
    from .keyword_match import KeywordMatcher

    data_dir = os.environ.get("TOCSIN_DATA_DIR")
    try:
        return KeywordMatcher.load(Path(data_dir) if data_dir else None)
    except (OSError, RuntimeError) as exc:
        print(
            f"stt-worker: could not load keyword trigger table, continuing without keyword "
            f"detection on live transcripts: {exc}",
            file=sys.stderr,
        )
        return None


def parse_chain(raw: str | None) -> set[str]:
    """`STT_CHAIN` (design doc §6): `local` (offgrid default), `local,remote`
    (hybrid race), or `remote` alone -- a deployment that transcribes
    entirely against a remote endpoint and never stages a local model.
    Empty/unset means `local`."""
    chain = {part.strip() for part in (raw or "").split(",") if part.strip()}
    return chain or {"local"}


def _build_remote_run(chain: set[str]):
    """Remote is enabled only if a base URL is actually configured -- a
    hybrid-only misconfiguration must never block the local-only path that
    works off-grid too (CLAUDE.md's connectivity rule), so this warns and
    falls back rather than exiting. `main()` handles the one case that
    can't fall back: `remote` with no `local` behind it."""
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
    heartbeat=None,
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
    working one on a night with no captures.

    The heartbeat has to keep beating throughout, or the wait is
    indistinguishable from a crash on the status board -- which is exactly
    how a deployment that never staged a model came to read as
    "stt-worker: no heartbeat" for hours."""
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
        if heartbeat is not None:
            heartbeat.beat(waiting_for_model=model_path)
        sleep(poll_interval_seconds)
        if clock() - last_reminder >= reminder_interval_seconds:
            print(f"stt-worker: still waiting for a model file at {model_path!r}.", file=sys.stderr, flush=True)
            last_reminder = clock()
    print(f"stt-worker: model file {model_path!r} appeared -- starting.", file=sys.stderr, flush=True)


def main() -> None:
    connect_addr = os.environ.get("STT_WORKER_ZMQ_CONNECT", DEFAULT_ZMQ_CONNECT)
    model_path = os.environ.get("STT_WORKER_MODEL_PATH")
    chain = parse_chain(os.environ.get("STT_CHAIN"))
    local_enabled = "local" in chain
    remote_run = _build_remote_run(chain)

    if not local_enabled and remote_run is None:
        # The only unrecoverable chain: remote asked for, no base URL to
        # reach, and no local transcription behind it to fall back to.
        print(
            "stt-worker: STT_CHAIN=remote needs STT_WORKER_REMOTE_BASE_URL, and there is no local "
            "provider to fall back to -- refusing to start",
            file=sys.stderr,
        )
        sys.exit(1)

    redis_client = _build_redis_client()
    heartbeat = heartbeat_module.build(redis_client)

    if local_enabled:
        # Off-grid means pre-staged, never download-on-first-boot (design
        # doc §8), so an unset path is a misconfiguration with nothing to
        # wait for. A *set* path that isn't there yet is the recoverable
        # case -- see `await_model`. A chain without `local` skips both:
        # a remote-only deployment has no reason to own a ggml model, and
        # blocking it here is what left stt-worker with no heartbeat and
        # no transcripts on a box that was never going to have one.
        if not model_path:
            print("stt-worker: STT_WORKER_MODEL_PATH is required -- refusing to start", file=sys.stderr)
            sys.exit(1)
        await_model(model_path, heartbeat=heartbeat)

    work_dir = Path(os.environ.get("STT_WORKER_WORK_DIR", str(DEFAULT_WORK_DIR)))
    language = os.environ.get("STT_WORKER_LANGUAGE", whispercpp.DEFAULT_LANGUAGE)
    initial_prompt = os.environ.get("STT_WORKER_INITIAL_PROMPT") or None
    binary = os.environ.get("STT_WORKER_WHISPER_BINARY", whispercpp.DEFAULT_BINARY)
    remote_budget_seconds = float(
        os.environ.get("STT_WORKER_REMOTE_BUDGET_SECONDS", DEFAULT_REMOTE_BUDGET_SECONDS)
    )
    live_allow_remote = os.environ.get("LIVE_TRANSCRIPTION_ALLOW_REMOTE", "false").strip().lower() in {"true", "1", "yes", "on"}

    subscriber = CaptureSubscriber(connect_addr)
    worker = TranscriptionWorker(
        model_path,
        work_dir,
        sink=_build_sink(redis_client),
        binary=binary,
        language=language,
        initial_prompt=initial_prompt,
        local_enabled=local_enabled,
        remote_run=remote_run,
        remote_budget_seconds=remote_budget_seconds,
        keyword_matcher=_build_keyword_matcher(),
        keyword_sink=_build_keyword_sink(redis_client),
        live_allow_remote=live_allow_remote,
    )
    chain_label = ",".join(sorted(chain))
    model_label = Path(model_path).name if local_enabled and model_path else "none (remote only)"
    print(f"stt-worker: subscribed to {connect_addr}, chain={chain_label}, model={model_label}", flush=True)
    try:
        while True:
            if heartbeat is not None:
                heartbeat.beat(model=model_label, chain=chain_label)
            payload = subscriber.recv(timeout_ms=1000)
            if payload is None:
                continue
            try:
                worker.handle_capture(payload)
            except Exception as exc:
                # One bad capture -- a remote endpoint that 500s, a WAV
                # that vanished from the shared volume -- must not take the
                # worker down and drop every *later* capture with it. The
                # audio is still on disk and the header still reached
                # fusion, so the loss is one transcript, not an alert.
                print(f"stt-worker: capture failed: {exc}", file=sys.stderr, flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        subscriber.close()
