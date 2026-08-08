"""Wires the capture-ready payload, WAV trimming, whisper.cpp provider,
and hallucination guard into one transcription pipeline (design doc §6).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from . import whispercpp
from .guard import check_transcript
from .trim import trim_wav


@dataclass(frozen=True)
class GuardedTranscript:
    site: str
    channel: str
    event_code: str
    fips_codes: tuple[str, ...]
    text: str
    passed_guard: bool
    guard_reason: str | None
    timestamp_ns: int


class TranscriptSink(Protocol):
    def record(self, transcript: GuardedTranscript) -> None: ...


class LoggingTranscriptSink:
    """Default sink: one JSON line per transcript on stdout. No Redis
    Streams/fusion consumer exists yet (that's Phase 5) -- same rationale
    as `same_decoder.service.LoggingEventSink`."""

    def record(self, transcript: GuardedTranscript) -> None:
        print(json.dumps(asdict(transcript)), flush=True)


class TranscriptionWorker:
    def __init__(
        self,
        model_path: str,
        work_dir: Path,
        sink: TranscriptSink | None = None,
        binary: str = whispercpp.DEFAULT_BINARY,
        language: str = whispercpp.DEFAULT_LANGUAGE,
        initial_prompt: str | None = None,
        whisper_run=whispercpp.run,
    ):
        self._model_path = model_path
        self._work_dir = work_dir
        self._sink = sink or LoggingTranscriptSink()
        self._binary = binary
        self._language = language
        self._initial_prompt = initial_prompt
        self._whisper_run = whisper_run

    def handle_capture(self, payload: dict) -> None:
        wav_path = Path(payload["wav_path"])
        trimmed_path = self._work_dir / f"trimmed-{wav_path.name}"
        trim_wav(wav_path, trimmed_path, payload.get("voice_start_sample"))

        transcript = self._whisper_run(
            trimmed_path,
            self._model_path,
            binary=self._binary,
            language=self._language,
            initial_prompt=self._initial_prompt,
        )
        result = check_transcript(transcript)
        self._sink.record(
            GuardedTranscript(
                site=payload["site"],
                channel=payload["channel"],
                event_code=payload["event_code"],
                fips_codes=tuple(payload["fips_codes"]),
                text=transcript.text if result.passed else "",
                passed_guard=result.passed,
                guard_reason=result.reason,
                timestamp_ns=time.time_ns(),
            )
        )
