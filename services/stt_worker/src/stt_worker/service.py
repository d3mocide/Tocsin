"""Wires the capture-ready payload, WAV trimming, STT provider(s), and
hallucination guard into one transcription pipeline (design doc §6).
"""

from __future__ import annotations

import concurrent.futures
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Protocol

from . import whispercpp
from .guard import check_transcript
from .transcript import Transcript
from .trim import trim_wav

DEFAULT_REMOTE_BUDGET_SECONDS = 10.0


@dataclass(frozen=True)
class GuardedTranscript:
    site: str
    channel: str
    event_code: str
    tier: str
    fips_codes: tuple[str, ...]
    raw_header: str
    text: str
    passed_guard: bool
    guard_reason: str | None
    timestamp_ns: int
    # The untrimmed capture on the shared `segment-captures` volume,
    # threaded straight through from segment_capture's payload. Carried so
    # `api` can serve the original audio next to the transcript -- a
    # transcript that failed the hallucination guard is exactly the one
    # worth listening to, and without this the WAV is unreachable from
    # anywhere but the container filesystem.
    wav_path: str | None = None


class TranscriptSink(Protocol):
    def record(self, transcript: GuardedTranscript) -> None: ...


class LoggingTranscriptSink:
    """Default sink: one JSON line per transcript on stdout. Stands in for
    `redis_sink.RedisStreamTranscriptSink` when no Redis URL is configured
    (local/test runs) -- same seam pattern as every other service's
    `LoggingXSink`."""

    def record(self, transcript: GuardedTranscript) -> None:
        print(json.dumps(asdict(transcript)), flush=True)


class TranscriptionWorker:
    """`remote_run`, when given, implements design doc §6's "race, don't
    chain" selection: `STT_CHAIN=local` (offgrid) leaves it `None` and
    every capture transcribes locally only; `STT_CHAIN=local,remote`
    (hybrid) races both concurrently on Tier A captures (Tier B stays
    local-only -- design doc §6). Local is always waited for in full (`"the
    floor... always completes"`); remote gets up to `remote_budget_seconds`
    *from the start of the race*, not a fresh clock after local finishes.

    "Remote wins if it returns within budget with a better score" (design
    doc §6) simplifies here to "remote wins if it returns within budget
    with non-empty text": a real cross-provider confidence comparison
    isn't implementable against a generic OpenAI-compatible endpoint --
    the standard `/v1/audio/transcriptions` response is just `{"text":
    ...}`, with no `no_speech_prob`/`avg_logprob`-equivalent guaranteed
    (see `remote_http.py`'s docstring). Whatever provider wins still goes
    through the same `check_transcript` guard below either way.
    """

    def __init__(
        self,
        model_path: str,
        work_dir: Path,
        sink: TranscriptSink | None = None,
        binary: str = whispercpp.DEFAULT_BINARY,
        language: str = whispercpp.DEFAULT_LANGUAGE,
        initial_prompt: str | None = None,
        whisper_run=whispercpp.run,
        remote_run: Callable[[Path], Transcript] | None = None,
        remote_budget_seconds: float = DEFAULT_REMOTE_BUDGET_SECONDS,
    ):
        self._model_path = model_path
        self._work_dir = work_dir
        self._sink = sink or LoggingTranscriptSink()
        self._binary = binary
        self._language = language
        self._initial_prompt = initial_prompt
        self._whisper_run = whisper_run
        self._remote_run = remote_run
        self._remote_budget_seconds = remote_budget_seconds

    def handle_capture(self, payload: dict) -> None:
        wav_path = Path(payload["wav_path"])
        trimmed_path = self._work_dir / f"trimmed-{wav_path.name}"
        trim_wav(wav_path, trimmed_path, payload.get("voice_start_sample"))

        transcript = self._transcribe(trimmed_path, payload.get("tier"))
        result = check_transcript(transcript)
        self._sink.record(
            GuardedTranscript(
                site=payload["site"],
                channel=payload["channel"],
                event_code=payload["event_code"],
                tier=payload["tier"],
                fips_codes=tuple(payload["fips_codes"]),
                raw_header=payload["raw_header"],
                text=transcript.text if result.passed else "",
                passed_guard=result.passed,
                guard_reason=result.reason,
                timestamp_ns=time.time_ns(),
                wav_path=str(wav_path),
            )
        )

    def _run_local(self, trimmed_path: Path) -> Transcript:
        return self._whisper_run(
            trimmed_path,
            self._model_path,
            binary=self._binary,
            language=self._language,
            initial_prompt=self._initial_prompt,
        )

    def _transcribe(self, trimmed_path: Path, tier: str | None) -> Transcript:
        if self._remote_run is None or tier != "A":
            return self._run_local(trimmed_path)

        start = time.monotonic()
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        try:
            local_future = pool.submit(self._run_local, trimmed_path)
            remote_future = pool.submit(self._remote_run, trimmed_path)

            local_transcript = local_future.result()  # the floor -- always waited for in full
            remaining_budget = max(0.0, self._remote_budget_seconds - (time.monotonic() - start))
            try:
                remote_transcript = remote_future.result(timeout=remaining_budget)
            except Exception:
                # Timeout, network error, or any remote failure -- local is
                # already in hand, so a remote hiccup degrades quality,
                # never availability (design doc §6's stated tradeoff).
                return local_transcript
        finally:
            # wait=False, not a `with` block: a `with`'s implicit
            # shutdown(wait=True) would block here until the remote
            # thread's own HTTP call resolves, even after we've already
            # given up waiting for it above -- that would silently turn
            # `remote_budget_seconds` into a lie. remote_http.run()'s own
            # `timeout_seconds` still bounds how long that background
            # thread can live, so nothing leaks indefinitely.
            pool.shutdown(wait=False)

        return remote_transcript if remote_transcript.text else local_transcript
