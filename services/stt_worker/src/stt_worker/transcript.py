"""Provider-agnostic transcript value types, shared by every STT provider
(design doc §6's uniform 16 kHz mono s16le input contract has a mirror on
the output side: every provider hands back the same shape regardless of
whether it ran locally or remotely).

Moved out of `whispercpp.py` now that a second real provider
(`remote_http.py`) exists to share it with -- CLAUDE.md's stated exception
to "stay concrete": generalize once there are two real things to
generalize from, not before. `whispercpp.py` re-exports both names so
existing imports (`from stt_worker.whispercpp import Transcript`) keep
working unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    text: str
    no_speech_prob: float | None
    avg_logprob: float | None


@dataclass(frozen=True)
class Transcript:
    text: str
    segments: tuple[Segment, ...]
