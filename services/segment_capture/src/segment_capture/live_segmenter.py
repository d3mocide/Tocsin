"""Continuous, VAD-segmented capture for the single configured "live
transcription" channel (docs/design/master-prompt.md's live-transcription
addendum to §4/§6) -- independent of SAME/ZCZC detection entirely, so
stt_worker gets a rolling stream of WAV chunks off ordinary NWR narration,
not just alert voice messages.

Unlike `SegmentRecorder` (design doc §4's ZCZC-to-EOM window), there is no
start/end event to key off of -- NWR broadcasts continuously. This instead
polls the same ring buffer `sdr_rx` already writes (`ring_reader.py`) and
cuts a WAV chunk itself: a simple energy-based speech/silence classifier
with hysteresis (a run of low-RMS frames after some accumulated speech
ends the chunk) plus a hard max-chunk-duration cap, since NWR's
synthesized voice regularly produces long uninterrupted narration that
would otherwise grow one chunk without bound.

`DEFAULT_RMS_THRESHOLD` is a starting point, not a calibrated constant --
like the design doc's own Whisper RTF numbers (master prompt §12), this
needs verification against a real discriminator feed on target hardware
and is exposed as an env var (`__init__.py`) for that reason.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .ring_reader import RING_BUFFER_SAMPLE_RATE_HZ, RingBufferReader
from .writer import write_wav

DEFAULT_MIN_CHUNK_SECONDS = 3.0
DEFAULT_MAX_CHUNK_SECONDS = 20.0
DEFAULT_SILENCE_HANG_SECONDS = 1.0
DEFAULT_RMS_THRESHOLD = 0.02  # normalized float32 discriminator output -- see module docstring
FRAME_SECONDS = 0.05


@dataclass(frozen=True)
class LiveCaptureResult:
    site: str
    channel: str
    wav_path: Path
    num_samples: int


@dataclass
class LiveSegmenterStats:
    """Observed audio levels since the last drain, for the periodic status
    line `service.py` prints.

    This exists because `DEFAULT_RMS_THRESHOLD` is explicitly uncalibrated
    (module docstring, and master prompt §12's open item): without the
    measured levels next to the configured threshold, a threshold set too
    high is indistinguishable from a dead channel -- both are simply
    silence, forever, with nothing in the log either way. Reporting both
    turns calibration into reading one line."""

    frames: int = 0
    speech_frames: int = 0
    peak_rms: float = 0.0
    sum_rms: float = 0.0
    chunks: int = 0

    @property
    def mean_rms(self) -> float:
        return self.sum_rms / self.frames if self.frames else 0.0


class LiveSegmenter:
    """One instance per continuously-transcribed (site, channel).

    `poll()` should be called often (`SegmentCaptureService.tick()`, every
    main-loop iteration) -- it drains whatever the ring buffer has
    accumulated since the last call, classifies speech/silence frame by
    frame, and returns every chunk finalized in that span (usually zero or
    one, but a slow poller draining a large backlog could cross more than
    one cut point at once, so this returns a list rather than dropping any
    but the first). A chunk that never saw speech (dead air, carrier hiss
    between announcements) is dropped rather than returned -- shipping it
    to stt_worker would just feed the hallucination guard silence it
    exists to catch.
    """

    def __init__(
        self,
        site: str,
        channel: str,
        ring_reader: RingBufferReader,
        output_dir: Path,
        min_chunk_seconds: float = DEFAULT_MIN_CHUNK_SECONDS,
        max_chunk_seconds: float = DEFAULT_MAX_CHUNK_SECONDS,
        silence_hang_seconds: float = DEFAULT_SILENCE_HANG_SECONDS,
        rms_threshold: float = DEFAULT_RMS_THRESHOLD,
        now_fn=time.time,
    ):
        self.site = site
        self.channel = channel
        self._ring_reader = ring_reader
        self._output_dir = output_dir
        self._min_chunk_samples = int(min_chunk_seconds * RING_BUFFER_SAMPLE_RATE_HZ)
        self._max_chunk_samples = int(max_chunk_seconds * RING_BUFFER_SAMPLE_RATE_HZ)
        self._silence_hang_samples = int(silence_hang_seconds * RING_BUFFER_SAMPLE_RATE_HZ)
        self._frame_samples = max(1, int(FRAME_SECONDS * RING_BUFFER_SAMPLE_RATE_HZ))
        self._rms_threshold = rms_threshold
        self._now = now_fn
        self._started = False
        self._chunks: list[np.ndarray] = []
        self._chunk_samples = 0
        self._speech_seen = False
        self._silence_run_samples = 0
        self._stats = LiveSegmenterStats()

    @property
    def rms_threshold(self) -> float:
        return self._rms_threshold

    def drain_stats(self) -> LiveSegmenterStats:
        """Returns the stats accumulated since the last call and resets
        them, so each periodic status line covers only its own window
        rather than all history."""
        stats, self._stats = self._stats, LiveSegmenterStats()
        return stats

    def poll(self) -> list[LiveCaptureResult]:
        if not self._started:
            # No preroll: unlike an alert capture, there's no detection
            # event to roll back before -- this just starts reading
            # forward from whatever the ring buffer's write pointer is
            # right now.
            self._ring_reader.start(0)
            self._started = True
        new_samples, _overrun = self._ring_reader.read_new()
        if new_samples.size == 0:
            return []
        return self._consume(new_samples)

    def _consume(self, samples: np.ndarray) -> list[LiveCaptureResult]:
        results = []
        for start in range(0, len(samples), self._frame_samples):
            frame = samples[start : start + self._frame_samples]
            self._chunks.append(frame)
            self._chunk_samples += len(frame)
            frame_rms = _rms(frame)
            self._stats.frames += 1
            self._stats.sum_rms += frame_rms
            self._stats.peak_rms = max(self._stats.peak_rms, frame_rms)
            if frame_rms >= self._rms_threshold:
                self._stats.speech_frames += 1
                self._speech_seen = True
                self._silence_run_samples = 0
            else:
                self._silence_run_samples += len(frame)

            hit_max = self._chunk_samples >= self._max_chunk_samples
            ready_to_cut = (
                self._speech_seen
                and self._chunk_samples >= self._min_chunk_samples
                and self._silence_run_samples >= self._silence_hang_samples
            )
            if hit_max or ready_to_cut:
                result = self._finalize()
                if result is not None:
                    results.append(result)
        return results

    def _finalize(self) -> LiveCaptureResult | None:
        speech_seen = self._speech_seen
        samples = np.concatenate(self._chunks) if self._chunks else np.zeros(0, dtype=np.float32)
        self._chunks = []
        self._chunk_samples = 0
        self._speech_seen = False
        self._silence_run_samples = 0
        if not speech_seen:
            return None
        filename = f"{self.site}-{self.channel}-live-{int(self._now() * 1000)}.wav"
        wav_path = self._output_dir / filename
        num_samples = write_wav(wav_path, samples)
        self._stats.chunks += 1
        return LiveCaptureResult(site=self.site, channel=self.channel, wav_path=wav_path, num_samples=num_samples)


def _rms(frame: np.ndarray) -> float:
    if frame.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(frame))))
