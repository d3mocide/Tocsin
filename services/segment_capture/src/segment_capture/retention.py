"""Age-based disk cleanup for the WAV files this service writes.

Nothing in the design doc gives `output_dir`/`live_output_dir` a retention
policy -- the same gap `alerts` had before the 2026-08-13 pruning sweep
(docs/design/tracking.md), except worse here: with `LIVE_TRANSCRIPTION_ENABLED`
on, `live_segmenter.py` cuts a new WAV every few seconds off NWR's own
looping narration, forever, and nothing ever removed one. That is a real
production incident, not a hypothetical -- it filled the `segment-captures`
volume.

Live chunks (`*-live-*.wav`, `live_segmenter.LiveSegmenter._finalize`) are
the disk hog and the least valuable to keep: most are transcribed and never
looked at again, so they default to a short retention window. SAME-triggered
alert captures (`recorder.SegmentRecorder._write`, no `-live-` segment in the
filename) are the rare, real thing an operator might want to keep around
after the fact, so they default to a much longer one.
"""

from __future__ import annotations

import time
from pathlib import Path

DEFAULT_LIVE_RETENTION_SECONDS = 86_400.0  # 1 day
DEFAULT_ALERT_RETENTION_SECONDS = 30 * 86_400.0  # 30 days

_LIVE_MARKER = "-live-"


def is_live_capture(path: Path) -> bool:
    return _LIVE_MARKER in path.name


def prune_captures(
    output_dir: Path,
    live_retention_seconds: float = DEFAULT_LIVE_RETENTION_SECONDS,
    alert_retention_seconds: float = DEFAULT_ALERT_RETENTION_SECONDS,
    now_fn=time.time,
) -> list[Path]:
    """Deletes every `*.wav` under `output_dir` older than its kind's
    retention window (by mtime, not by parsing the filename's embedded
    timestamp -- `write_wav` sets it at write time and it's what every
    other tool on the box already uses to reason about the file's age).

    Best-effort: this runs against a directory `recorder`/`live_segmenter`
    are actively writing into, so a file that disappears between the
    listing and the stat/unlink (finalized and picked up elsewhere, or
    another prune pass racing this one) is skipped rather than raised."""
    now = now_fn()
    deleted: list[Path] = []
    try:
        candidates = list(output_dir.glob("*.wav"))
    except OSError:
        return deleted
    for path in candidates:
        retention = live_retention_seconds if is_live_capture(path) else alert_retention_seconds
        try:
            age_seconds = now - path.stat().st_mtime
        except OSError:
            continue
        if age_seconds < retention:
            continue
        try:
            path.unlink()
        except OSError:
            continue
        deleted.append(path)
    return deleted
