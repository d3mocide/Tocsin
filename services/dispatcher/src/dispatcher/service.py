"""Wires stage 1 (tier gating, dedup, rate limiting, idempotency, template
message, Meshtastic egress -- design doc §7, roadmap.md Phase 6) and
stage 2 (LiteLLM enrichment with a circuit breaker, output validation,
the same egress -- Phase 7) into two dispatch pipelines sharing the same
idempotency/egress machinery.

Gate order matters in both, not just for readability: side-effecting
checks (`dedup`, `idempotency.claim()`) are ordered so that the *last*
thing before a send is always `idempotency.claim()`. `claim()` has a 24h
side effect on success -- if it ran earlier and a later gate then rejected
the message, that message would be permanently stranded as "already sent"
for 24h despite never actually going out. Stage 2 additionally uses
`idempotency.already_claimed()` (no side effect) as an *early* gate before
the paid LiteLLM call, purely to avoid spending money re-enriching
something already fully dispatched -- the real, authoritative gate is
still the `claim()` call right before the send.

Tier gating (design doc §4): only Tier A reaches the mesh at all. Tier B/C
alerts are simply logged as skipped here, not queued for a later stage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Union

from .circuit_breaker import CircuitBreaker
from .dedup import AlertDeduplicator
from .egress.dispatch import MeshSender
from .fips import FipsTable
from .idempotency import IdempotencyStore
from .litellm_client import LiteLLMClient
from .message import build_stage1_message
from .models import RFAlertIn, TranscriptIn
from .rate_limit import TokenBucket
from .stage2_guard import check_stage2_output

TIER_A = "A"
STAGE_1 = "1"
STAGE_2 = "2"


@dataclass(frozen=True)
class DispatchOutcome:
    sent: bool
    reason: str


DispatchInput = Union[RFAlertIn, TranscriptIn]


class DispatchLog(Protocol):
    def record(self, item: DispatchInput, outcome: DispatchOutcome) -> None: ...


class LoggingDispatchLog:
    def record(self, item: DispatchInput, outcome: DispatchOutcome) -> None:
        print(
            f"dispatcher: {item.event_code} {list(item.fips_codes)} -> {outcome.reason}",
            flush=True,
        )


class Stage1Dispatcher:
    def __init__(
        self,
        fips_table: FipsTable,
        idempotency: IdempotencyStore,
        dedup: AlertDeduplicator,
        rate_limiter: TokenBucket,
        egress: MeshSender,
        log: DispatchLog | None = None,
    ):
        self._fips_table = fips_table
        self._idempotency = idempotency
        self._dedup = dedup
        self._rate_limiter = rate_limiter
        self._egress = egress
        self._log = log or LoggingDispatchLog()

    def handle(self, alert: RFAlertIn) -> DispatchOutcome:
        outcome = self._evaluate(alert)
        self._log.record(alert, outcome)
        return outcome

    def _evaluate(self, alert: RFAlertIn) -> DispatchOutcome:
        if alert.tier != TIER_A:
            return DispatchOutcome(sent=False, reason="skipped_not_tier_a")
        if self._dedup.is_duplicate(alert.event_code, alert.fips_codes):
            return DispatchOutcome(sent=False, reason="skipped_duplicate")
        if not self._rate_limiter.try_acquire():
            return DispatchOutcome(sent=False, reason="skipped_rate_limited")
        if not self._idempotency.claim(alert.raw_header, stage=STAGE_1):
            return DispatchOutcome(sent=False, reason="skipped_already_sent")

        message = build_stage1_message(
            alert.event_code, alert.fips_codes, alert.purge_minutes, alert.received_at, self._fips_table
        )
        try:
            result = self._egress.send(message)
        except Exception:
            # The idempotency key is already claimed at this point (see
            # this module's docstring) -- a transient failure here means
            # this exact alert won't be retried until its 24h claim
            # expires. An accepted, explicitly-scoped gap (README.md).
            return DispatchOutcome(sent=True, reason="send_error")
        return DispatchOutcome(sent=result.delivered, reason=result.path)


class Stage2Dispatcher:
    """Tier A only, and only for a transcript that already passed
    `stt_worker`'s own hallucination guard (`passed_guard`/`text` --
    that's a *different* guard than `stage2_guard.check_stage2_output`,
    which validates LiteLLM's output, not the transcript LiteLLM never
    should have received in the first place if it looked hallucinated).
    """

    def __init__(
        self,
        idempotency: IdempotencyStore,
        circuit_breaker: CircuitBreaker,
        litellm_client: LiteLLMClient,
        egress: MeshSender,
        log: DispatchLog | None = None,
    ):
        self._idempotency = idempotency
        self._circuit_breaker = circuit_breaker
        self._litellm_client = litellm_client
        self._egress = egress
        self._log = log or LoggingDispatchLog()

    def handle(self, transcript: TranscriptIn) -> DispatchOutcome:
        outcome = self._evaluate(transcript)
        self._log.record(transcript, outcome)
        return outcome

    def _evaluate(self, transcript: TranscriptIn) -> DispatchOutcome:
        if transcript.tier != TIER_A:
            return DispatchOutcome(sent=False, reason="skipped_not_tier_a")
        if not transcript.passed_guard or not transcript.text:
            return DispatchOutcome(sent=False, reason="skipped_no_transcript")
        if self._idempotency.already_claimed(transcript.raw_header, stage=STAGE_2):
            return DispatchOutcome(sent=False, reason="skipped_already_sent")
        if self._circuit_breaker.is_open():
            return DispatchOutcome(sent=False, reason="skipped_circuit_open")

        try:
            impact_clause = self._litellm_client.compress(transcript.text, max_bytes=200)
        except Exception:
            # Any failure -> stage 2 is silently skipped (design doc §7).
            # Stage 1 already delivered, so this degrades detail, never
            # delivery.
            self._circuit_breaker.record_failure()
            return DispatchOutcome(sent=False, reason="skipped_litellm_failure")
        self._circuit_breaker.record_success()

        guard_result = check_stage2_output(impact_clause)
        if not guard_result.passed:
            return DispatchOutcome(sent=False, reason=f"skipped_output_guard:{guard_result.reason}")

        if not self._idempotency.claim(transcript.raw_header, stage=STAGE_2):
            return DispatchOutcome(sent=False, reason="skipped_already_sent")

        try:
            result = self._egress.send(impact_clause)
        except Exception:
            return DispatchOutcome(sent=True, reason="send_error")
        return DispatchOutcome(sent=result.delivered, reason=result.path)
