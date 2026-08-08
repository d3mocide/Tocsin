"""Hallucination guards for whisper.cpp transcripts (design doc §6): NWR
is full of tone-heavy and near-silent audio, and Whisper emits confident
garbage on both. An unguarded transcript feeding LiteLLM feeding a mesh
broadcast is called out there as the worst failure chain in this system --
treat this as a correctness requirement, not a polish item.

The `no_speech_prob`/`avg_logprob` threshold checks only fire when
whisper.cpp actually supplies that field for a segment -- see
`whispercpp.py`'s docstring for why neither is guaranteed present on every
build. The blocklist check is unconditional and is this guard's one
guarantee regardless of whisper.cpp version.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .whispercpp import Transcript

DEFAULT_NO_SPEECH_PROB_THRESHOLD = 0.6
DEFAULT_AVG_LOGPROB_THRESHOLD = -1.0

# Classic Whisper hallucinations on silence/tone-heavy audio: stock
# subtitle/credit phrases it emits with high confidence despite there
# being no actual speech in the source audio.
DEFAULT_BLOCKLIST_PATTERNS = (
    r"thank(s| you) for watching",
    r"subscribe to (my|the) channel",
    r"like and subscribe",
    r"\bcaption(ed|ing)? by\b",
    r"amara\.org",
)


@dataclass(frozen=True)
class GuardResult:
    passed: bool
    reason: str | None


def _blocklist_match(text: str, patterns: tuple[str, ...]) -> str | None:
    lowered = text.lower()
    for pattern in patterns:
        if re.search(pattern, lowered):
            return pattern
    return None


def check_transcript(
    transcript: Transcript,
    no_speech_prob_threshold: float = DEFAULT_NO_SPEECH_PROB_THRESHOLD,
    avg_logprob_threshold: float = DEFAULT_AVG_LOGPROB_THRESHOLD,
    blocklist_patterns: tuple[str, ...] = DEFAULT_BLOCKLIST_PATTERNS,
) -> GuardResult:
    blocked = _blocklist_match(transcript.text, blocklist_patterns)
    if blocked is not None:
        return GuardResult(passed=False, reason=f"blocklist match: {blocked!r}")

    for segment in transcript.segments:
        if segment.no_speech_prob is not None and segment.no_speech_prob >= no_speech_prob_threshold:
            return GuardResult(
                passed=False,
                reason=f"no_speech_prob {segment.no_speech_prob} >= {no_speech_prob_threshold}",
            )
        if segment.avg_logprob is not None and segment.avg_logprob <= avg_logprob_threshold:
            return GuardResult(
                passed=False,
                reason=f"avg_logprob {segment.avg_logprob} <= {avg_logprob_threshold}",
            )

    return GuardResult(passed=True, reason=None)
