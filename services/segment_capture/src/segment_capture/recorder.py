"""Per-(site, channel) SAME message capture (design doc §4): starts on
ZCZC detect, ends on EOM or a hard timeout, accumulates the full segment
from the ring buffer (pre-roll + live drain -- see `ring_reader.py`), and
finalizes into a WAV file plus voice-start boundary metadata.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .boundary import MessageStart
from .ring_reader import RING_BUFFER_SAMPLE_RATE_HZ, RingBufferReader
from .tone import find_voice_start_sample
from .writer import ring_rate_sample_to_stt_rate, write_wav

DEFAULT_PREROLL_SECONDS = 10.0
DEFAULT_HARD_TIMEOUT_SECONDS = 300.0


@dataclass(frozen=True)
class CaptureResult:
    site: str
    channel: str
    event_code: str
    fips_codes: tuple[str, ...]
    wav_path: Path
    voice_start_sample: int | None  # STT-rate (16 kHz) offset into the WAV, or None if undetected
    num_samples: int
    timed_out: bool
    had_gap: bool


class SegmentRecorder:
    """One capture in progress for one (site, channel). `service.py` owns
    one of these per active key, created on `MessageStart` and discarded
    after `finalize()`."""

    def __init__(
        self,
        site: str,
        channel: str,
        message_start: MessageStart,
        ring_reader: RingBufferReader,
        output_dir: Path,
        preroll_seconds: float = DEFAULT_PREROLL_SECONDS,
        hard_timeout_seconds: float = DEFAULT_HARD_TIMEOUT_SECONDS,
        now_fn=time.monotonic,
    ):
        self.site = site
        self.channel = channel
        self._message_start = message_start
        self._ring_reader = ring_reader
        self._output_dir = output_dir
        self._hard_timeout_seconds = hard_timeout_seconds
        self._now = now_fn
        self._started_at = self._now()
        self._had_gap = False
        preroll_samples = int(preroll_seconds * RING_BUFFER_SAMPLE_RATE_HZ)
        self._chunks: list[np.ndarray] = [ring_reader.start(preroll_samples)]

    def poll(self) -> None:
        """Call more often than the ring buffer's 30s wraparound while a
        capture is in progress, to drain newly-written audio before it's
        overwritten."""
        new_samples, overrun = self._ring_reader.read_new()
        if overrun:
            self._had_gap = True
        if new_samples.size:
            self._chunks.append(new_samples)

    def timed_out(self) -> bool:
        return self._now() - self._started_at >= self._hard_timeout_seconds

    def finalize(self, timed_out: bool) -> CaptureResult:
        self.poll()  # capture anything written since the last poll
        samples = np.concatenate(self._chunks) if self._chunks else np.zeros(0, dtype=np.float32)
        voice_start_ring = find_voice_start_sample(samples, RING_BUFFER_SAMPLE_RATE_HZ)
        voice_start_stt = ring_rate_sample_to_stt_rate(voice_start_ring) if voice_start_ring is not None else None
        filename = f"{self.site}-{self.channel}-{self._message_start.event_code}-{int(time.time())}.wav"
        wav_path = self._output_dir / filename
        num_samples = write_wav(wav_path, samples)
        return CaptureResult(
            site=self.site,
            channel=self.channel,
            event_code=self._message_start.event_code,
            fips_codes=self._message_start.fips_codes,
            wav_path=wav_path,
            voice_start_sample=voice_start_stt,
            num_samples=num_samples,
            timed_out=timed_out,
            had_gap=self._had_gap,
        )
