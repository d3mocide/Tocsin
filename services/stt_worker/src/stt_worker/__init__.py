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

from . import whispercpp
from .service import TranscriptionWorker
from .subscriber import CaptureSubscriber

DEFAULT_ZMQ_CONNECT = "tcp://segment-capture:5556"
DEFAULT_WORK_DIR = Path("/tmp/stt_worker")


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

    subscriber = CaptureSubscriber(connect_addr)
    worker = TranscriptionWorker(
        model_path, work_dir, binary=binary, language=language, initial_prompt=initial_prompt
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
