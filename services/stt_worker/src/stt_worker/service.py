"""Wires the capture-ready payload, WAV trimming, STT provider(s), and
hallucination guard into one transcription pipeline (design doc §6).
"""

from __future__ import annotations

import concurrent.futures
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Protocol

from . import whispercpp
from .guard import check_transcript
from .keyword_match import KeywordMatcher
from .transcript import Transcript
from .trim import trim_wav

DEFAULT_REMOTE_BUDGET_SECONDS = 10.0

# `capture_kind == "live"` transcripts (the live-transcription addendum to
# design doc §4/§6) carry no SAME header at all, so there's no real
# event_code/tier to report -- these stand in rather than leaving the
# columns null, matching the "ambient narration, not a hazard" tier
# dispatcher's existing Tier A/B/C gating already understands (Tier C:
# log-only). A keyword match found *within* that text still gets its own,
# separate event_code/tier from `keyword_match.KeywordMatcher` -- this
# constant is only for the raw transcript record itself.
LIVE_EVENT_CODE = "LIVE"
LIVE_TIER = "C"


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
    # "alert" (SAME-triggered, the original and still default shape) or
    # "live" (continuous, VAD-cut -- segment_capture.bus's own
    # discriminator field, threaded straight through).
    capture_kind: str = "alert"


class TranscriptSink(Protocol):
    def record(self, transcript: GuardedTranscript) -> None: ...


class LoggingTranscriptSink:
    """Default sink: one JSON line per transcript on stdout. Stands in for
    `redis_sink.RedisStreamTranscriptSink` when no Redis URL is configured
    (local/test runs) -- same seam pattern as every other service's
    `LoggingXSink`."""

    def record(self, transcript: GuardedTranscript) -> None:
        print(json.dumps(asdict(transcript)), flush=True)


@dataclass(frozen=True)
class KeywordEvent:
    """One keyword-matched hazard phrase found in a live transcript
    (`keyword_match.py`) -- `fusion` consumes this the same way it
    consumes a SAME event, just from a much fuzzier source (design doc's
    live-transcription addendum to §5): a `TRANSCRIPT_ONLY` alert, never
    dispatched over the mesh."""

    site: str
    channel: str
    event_code: str
    event_name: str
    tier: str
    matched_phrase: str
    transcript_text: str
    timestamp_ns: int


class KeywordEventSink(Protocol):
    def record(self, event: KeywordEvent) -> None: ...


class LoggingKeywordEventSink:
    def record(self, event: KeywordEvent) -> None:
        print(json.dumps(asdict(event)), flush=True)


class TranscriptionWorker:
    """`remote_run`, when given, implements design doc §6's "race, don't
    chain" selection: `STT_CHAIN=local` (offgrid) leaves it `None` and
    every capture transcribes locally only; `STT_CHAIN=local,remote`
    (hybrid) races both concurrently on Tier A captures (Tier B stays
    local-only -- design doc §6). Local is always waited for in full (`"the
    floor... always completes"`); remote gets up to `remote_budget_seconds`
    *from the start of the race*, not a fresh clock after local finishes.

    `local_enabled=False` (`STT_CHAIN=remote`) is the hybrid-only case with
    no floor at all: no ggml model is staged, `model_path` may be `None`,
    and every capture goes to the remote endpoint. Off-grid deployments
    must never be configured this way -- it makes transcription depend on
    the network, which CLAUDE.md's connectivity rule forbids for a core
    path -- but a hybrid box transcribing against a remote endpoint has no
    reason to carry a model it will never load.

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
        model_path: str | None,
        work_dir: Path,
        sink: TranscriptSink | None = None,
        binary: str = whispercpp.DEFAULT_BINARY,
        language: str = whispercpp.DEFAULT_LANGUAGE,
        initial_prompt: str | None = None,
        whisper_run=whispercpp.run,
        local_enabled: bool = True,
        remote_run: Callable[[Path], Transcript] | None = None,
        remote_budget_seconds: float = DEFAULT_REMOTE_BUDGET_SECONDS,
        keyword_matcher: KeywordMatcher | None = None,
        keyword_sink: KeywordEventSink | None = None,
    ):
        self._model_path = model_path
        self._local_enabled = local_enabled
        self._work_dir = work_dir
        self._sink = sink or LoggingTranscriptSink()
        self._binary = binary
        self._language = language
        self._initial_prompt = initial_prompt
        self._whisper_run = whisper_run
        self._remote_run = remote_run
        self._remote_budget_seconds = remote_budget_seconds
        # Both `None` unless the caller explicitly enables live
        # transcription (`__init__.py`) -- without a matcher, a "live"
        # capture still transcribes and records normally, it just never
        # produces a KeywordEvent.
        self._keyword_matcher = keyword_matcher
        self._keyword_sink = keyword_sink or LoggingKeywordEventSink()

    def handle_capture(self, payload: dict) -> None:
        capture_kind = payload.get("capture_kind", "alert")
        if capture_kind == "live" and not self._local_enabled:
            # No local floor to fall back to (`STT_CHAIN=remote` --
            # see the class docstring). Continuous transcription must
            # never depend on the network (CLAUDE.md's connectivity
            # rule), so this drops the chunk rather than spending a
            # remote call on every few seconds of ambient audio.
            return

        wav_path = Path(payload["wav_path"])
        trimmed_path = self._work_dir / f"trimmed-{wav_path.name}"
        trim_wav(wav_path, trimmed_path, payload.get("voice_start_sample"))

        if capture_kind == "live":
            # Local-only, never raced against remote: a live chunk is
            # ambient narration, not a Tier A alert enrichment, so it
            # never earns the network budget design doc §6 reserves for
            # Tier A captures.
            transcript = self._run_local(trimmed_path)
        else:
            transcript = self._transcribe(trimmed_path, payload.get("tier"))
        result = check_transcript(transcript)
        text = transcript.text if result.passed else ""

        guarded = GuardedTranscript(
            site=payload["site"],
            channel=payload["channel"],
            event_code=payload.get("event_code") or LIVE_EVENT_CODE,
            tier=payload.get("tier") or LIVE_TIER,
            fips_codes=tuple(payload.get("fips_codes", ())),
            raw_header=payload.get("raw_header") or f"live:{payload['site']}:{payload['channel']}",
            text=text,
            passed_guard=result.passed,
            guard_reason=result.reason,
            timestamp_ns=time.time_ns(),
            wav_path=str(wav_path),
            capture_kind=capture_kind,
        )
        self._sink.record(guarded)

        if capture_kind == "live":
            # The transcript itself, on stderr. With a Redis sink configured
            # (every compose deployment) a live transcript otherwise reaches
            # only Postgres and the UI, so `docker compose logs -f
            # stt-worker` showed nothing at all while continuous
            # transcription was working perfectly -- indistinguishable from
            # broken. This is the feature's proof of life.
            detail = text if result.passed else f"<withheld: {result.reason}>"
            print(
                f"stt-worker: live {guarded.site}/{guarded.channel}: {detail}",
                file=sys.stderr,
                flush=True,
            )

        if capture_kind == "live" and result.passed and text and self._keyword_matcher is not None:
            match = self._keyword_matcher.match(text)
            if match is not None:
                self._keyword_sink.record(
                    KeywordEvent(
                        site=guarded.site,
                        channel=guarded.channel,
                        event_code=match.event_code,
                        event_name=match.event_name,
                        tier=match.tier,
                        matched_phrase=match.matched_phrase,
                        transcript_text=text,
                        timestamp_ns=guarded.timestamp_ns,
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
        if not self._local_enabled:
            # `STT_CHAIN=remote`: no local floor exists, so remote takes
            # every tier rather than only Tier A. Tier B being local-only
            # (design doc §6) is a rule about not spending network on the
            # lower tier when a free local provider is right there; with
            # no local provider it would just mean silently dropping Tier
            # B transcripts.
            assert self._remote_run is not None  # main() refuses to start otherwise
            return self._remote_run(trimmed_path)
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
            except Exception as exc:
                # Timeout, network error, or any remote failure -- local is
                # already in hand, so a remote hiccup degrades quality,
                # never availability (design doc §6's stated tradeoff). Still
                # logged, though: silently swallowing this is what let a
                # remote endpoint fail on every single capture with nobody
                # noticing from stt-worker's own logs -- only the remote
                # backend's own dashboard showed it.
                print(f"stt-worker: remote STT failed, using local result instead: {exc!r}", file=sys.stderr, flush=True)
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
