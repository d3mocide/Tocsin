"""Trims a segment_capture WAV to its voice-only portion before inference
(design doc §6's first preprocessing step -- stripping the SAME header
burst and attention tone recovers a meaningful fraction of a Pi's
inference time, and feeding the tone itself to Whisper is a known
hallucination trigger; see `guard.py`).
"""

from __future__ import annotations

import wave
from pathlib import Path


def trim_wav(source_path: Path, dest_path: Path, voice_start_sample: int | None) -> None:
    """Writes a copy of `source_path` to `dest_path`, starting at
    `voice_start_sample` (an offset in `source_path`'s own sample rate, as
    reported by segment_capture -- see its `tone.py`). `None` means no
    tone boundary was found there; this copies the whole file rather than
    guessing a cut point."""
    with wave.open(str(source_path), "rb") as source:
        params = source.getparams()
        frames = source.readframes(source.getnframes())
    bytes_per_frame = params.sampwidth * params.nchannels
    start_byte = 0 if voice_start_sample is None else min(voice_start_sample, params.nframes) * bytes_per_frame
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dest_path), "wb") as dest:
        dest.setparams(params)
        dest.writeframes(frames[start_byte:])
