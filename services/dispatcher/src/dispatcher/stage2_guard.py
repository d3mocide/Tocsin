"""Output validation for stage 2's LiteLLM-compressed impact clause
(design doc §7): length, ASCII-only, no newlines.

Distinct from `stt_worker.guard`'s hallucination guard -- that one
validates whether the *transcript* (LiteLLM's input) is trustworthy; this
one validates LiteLLM's own *output* before it goes out over the mesh.
Any failure here means stage 2 is silently skipped -- stage 1 already
delivered, so a failure degrades detail, never delivery (design doc §7's
own stated posture: "Any failure => stage 2 is silently skipped").
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_BYTES = 200


@dataclass(frozen=True)
class Stage2GuardResult:
    passed: bool
    reason: str | None


def check_stage2_output(text: str, max_bytes: int = MAX_BYTES) -> Stage2GuardResult:
    if not text:
        return Stage2GuardResult(passed=False, reason="empty output")
    if "\n" in text or "\r" in text:
        return Stage2GuardResult(passed=False, reason="contains a newline")
    try:
        encoded = text.encode("ascii")
    except UnicodeEncodeError:
        return Stage2GuardResult(passed=False, reason="not ASCII")
    if len(encoded) > max_bytes:
        return Stage2GuardResult(passed=False, reason=f"exceeds {max_bytes} bytes")
    return Stage2GuardResult(passed=True, reason=None)
