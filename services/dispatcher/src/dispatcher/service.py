"""Wires tier gating, dedup, rate limiting, idempotency, stage-1 message
building, and the Meshtastic serial send into one dispatch pipeline
(design doc §7's stage 1, roadmap.md Phase 6).

Gate order matters, not just for readability: `dedup`/`rate_limit` are
checked *before* `idempotency.claim()`, and `claim()` is the very last
check before the send itself. `claim()` has a 24h side effect on success
-- if it ran first and a later gate then rejected the alert, that alert
would be permanently stranded as "already sent" for 24h despite never
actually going out. Putting it last means a `True` claim always
corresponds to "sending right now."

Tier gating (design doc §4): only Tier A reaches the mesh at all (Tier A:
"mesh + MQTT"; Tier B: "MQTT only"; Tier C: "log only") -- and this phase
doesn't build MQTT egress yet (that's Phase 7's Meshtastic MQTT
*ack-fallback* leg specifically, not a general Tier-B broadcast path,
which isn't clearly scoped to any named phase in roadmap.md as of this
writing). Tier B/C alerts are simply logged as skipped here, not queued
for a later stage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .dedup import AlertDeduplicator
from .fips import FipsTable
from .idempotency import IdempotencyStore
from .message import build_stage1_message
from .meshtastic_serial import MeshtasticSerialClient
from .models import RFAlertIn
from .rate_limit import TokenBucket

TIER_A = "A"
STAGE = "1"


@dataclass(frozen=True)
class DispatchOutcome:
    sent: bool
    reason: str


class DispatchLog(Protocol):
    def record(self, alert: RFAlertIn, outcome: DispatchOutcome) -> None: ...


class LoggingDispatchLog:
    def record(self, alert: RFAlertIn, outcome: DispatchOutcome) -> None:
        print(
            f"dispatcher: {alert.event_code} {list(alert.fips_codes)} -> {outcome.reason}",
            flush=True,
        )


class Stage1Dispatcher:
    def __init__(
        self,
        fips_table: FipsTable,
        idempotency: IdempotencyStore,
        dedup: AlertDeduplicator,
        rate_limiter: TokenBucket,
        mesh_client: MeshtasticSerialClient,
        log: DispatchLog | None = None,
    ):
        self._fips_table = fips_table
        self._idempotency = idempotency
        self._dedup = dedup
        self._rate_limiter = rate_limiter
        self._mesh_client = mesh_client
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
        if not self._idempotency.claim(alert.raw_header, stage=STAGE):
            return DispatchOutcome(sent=False, reason="skipped_already_sent")

        message = build_stage1_message(
            alert.event_code, alert.fips_codes, alert.purge_minutes, alert.received_at, self._fips_table
        )
        try:
            result = self._mesh_client.send_text(message)
        except Exception:
            # The idempotency key is already claimed at this point (see
            # this module's docstring) -- a transient serial error here
            # means this exact alert won't be retried until its 24h claim
            # expires, since the MQTT ack-fallback that would normally
            # cover a failed send doesn't exist yet (Phase 7). An accepted,
            # explicitly-scoped gap for this phase, not a silent one.
            return DispatchOutcome(sent=True, reason="send_error")
        return DispatchOutcome(sent=True, reason="sent" if result.acked else "no_ack")
