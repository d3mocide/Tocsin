"""Keyword-based hazard detection for continuously-transcribed audio
(docs/design/master-prompt.md's live-transcription addendum to §4/§6).

This is deliberately a backstop, not the primary detection path -- every
product NWS actually SAME-encodes on NWR is already caught by
`same_decoder` before a human (or this matcher) ever hears it. What this
catches is a product that never got a SAME header (a forecaster ad-lib
folded into routine narration) or one whose header `multimon-ng` failed to
decode under poor SNR. It only ever runs against `capture_kind == "live"`
transcripts that already passed `guard.py`'s hallucination guard
(`service.py`) -- a transcript reaching this that shouldn't have is a
strictly worse version of the same failure mode that guard exists to
prevent, one layer up.

Loads two checked-in tables independently (CLAUDE.md: shared reference
data lives once under `data/`, loaded per service rather than imported
across the boundary): `keyword_triggers.yaml` (phrase -> event code) and
`same_event_codes.yaml` (event code -> name/tier, the same table
`segment_capture.tiers.TierTable`/`same_decoder.tiers.TierTable` each load
independently), so a keyword match carries the exact same tier semantics
as a SAME-decoded one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

UNKNOWN_CODE_TIER = "B"


def _default_data_dir(module_file: str = __file__) -> Path:
    here = Path(module_file).resolve()
    parents = here.parents
    if len(parents) <= 4:
        raise RuntimeError(
            f"can't infer a default data/ directory from {here} (not a full source "
            "checkout) -- pass data_dir explicitly, or set TOCSIN_DATA_DIR"
        )
    return parents[4] / "data"


@dataclass(frozen=True)
class KeywordMatch:
    event_code: str
    event_name: str
    tier: str
    matched_phrase: str


class KeywordMatcher:
    def __init__(self, phrase_index: list[tuple[re.Pattern, str, KeywordMatch]]):
        # Sorted longest-phrase-first at construction (see `load()`) so
        # `match()` can just take the first hit.
        self._phrase_index = phrase_index

    @classmethod
    def load(cls, data_dir: Path | None = None) -> "KeywordMatcher":
        directory = data_dir or _default_data_dir()
        with (directory / "keyword_triggers.yaml").open() as f:
            triggers = yaml.safe_load(f) or {}
        with (directory / "same_event_codes.yaml").open() as f:
            codes = yaml.safe_load(f) or {}

        phrase_index: list[tuple[re.Pattern, str, KeywordMatch]] = []
        for event_code, entry in triggers.items():
            code_info = codes.get(event_code, {})
            event_name = code_info.get("name", f"Unknown event code {event_code}")
            tier = code_info.get("tier", UNKNOWN_CODE_TIER)
            for phrase in entry.get("phrases", []):
                pattern = re.compile(r"\b" + re.escape(phrase.lower()) + r"\b")
                phrase_index.append((pattern, phrase, KeywordMatch(event_code, event_name, tier, phrase)))

        # Longest phrase first: if two phrases in the table ever overlap
        # (e.g. a future "flash flood" alongside "flash flood warning"),
        # the more specific one should win.
        phrase_index.sort(key=lambda item: len(item[1]), reverse=True)
        return cls(phrase_index)

    def match(self, text: str) -> KeywordMatch | None:
        """First (longest-phrase) match only -- one live chunk is a few
        seconds of speech, realistically at most one hazard phrase, and
        fusion treats each match as its own event regardless."""
        lowered = text.lower()
        for pattern, _phrase, result in self._phrase_index:
            if pattern.search(lowered):
                return result
        return None
