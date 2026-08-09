"""Squelch and voice-band filtering for the STT/live-audio feed (Icecast
listening via `live_audio`) -- design doc §3 discriminator output is raw
phase-difference noise below FM capture threshold, and gets streamed
unfiltered otherwise.

Deliberately **not** applied to the SAME-decode topic, the health sample, or
the ring buffer `segment_capture` reads alert audio from (see pipeline.py):
a misfiring gate or a filter that rolls off part of the AFSK tone band would
risk clipping a real SAME header or warning clip, and CLAUDE.md's
"remain fully functional" bar applies to that path, not this one.

Both classes are chunk-streaming with carried filter state, the same shape
as `DCBlocker`/`FMDiscriminator`: `process()`/`envelope()` can be called
repeatedly on successive chunks and picks up where the last call left off.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfilt

from .resample import BIN_RATE_HZ

VOICE_BAND_LOW_HZ = 300.0
VOICE_BAND_HIGH_HZ = 3_000.0
VOICE_BAND_ORDER = 4

# Noise-detection band for the squelch: FM discriminator noise power rises
# with frequency (the classic "noise triangle"), while real NWR voice/tone
# content stays under ~3 kHz. Energy above 8 kHz is therefore a good proxy
# for "no signal captured" even though the raw discriminator has no SNR
# estimate of its own -- a real receiver squelch works the same way, on an
# above-audio noise band rather than absolute level, since level alone can't
# distinguish a strong carrier's noise floor from a weak one.
SQUELCH_NOISE_BAND_HZ = 8_000.0
SQUELCH_ORDER = 4
# Picked from synthetic no-carrier vs. carrier-present discriminator output
# (see test_audio_conditioning.py): full-scale phase noise measures ~1.5-1.8
# in this band, a strong carrier's residual floor ~0.04, and a noisy-but
# -present weak signal ~0.4 -- 0.6 sits with headroom on both sides. Retune
# with `SDR_RX_SQUELCH_THRESHOLD` per site; there's no universal value, same
# as gain (see capture.DEFAULT_GAIN_DB).
SQUELCH_DEFAULT_THRESHOLD = 0.6
SQUELCH_HANG_TIME_S = 0.3
SQUELCH_FADE_S = 0.005


class VoiceBandFilter:
    """Streaming Butterworth bandpass limiting discriminator output to NWR's
    voice bandwidth (~300 Hz-3 kHz). Most of what listeners hear as "static"
    on a marginal channel is discriminator noise outside this band; audio
    inside it is barely attenuated."""

    def __init__(
        self,
        sample_rate_hz: float = BIN_RATE_HZ,
        low_hz: float = VOICE_BAND_LOW_HZ,
        high_hz: float = VOICE_BAND_HIGH_HZ,
        order: int = VOICE_BAND_ORDER,
    ):
        self._sos = butter(order, [low_hz, high_hz], btype="bandpass", fs=sample_rate_hz, output="sos")
        self._zi = np.zeros((self._sos.shape[0], 2))

    def reset(self) -> None:
        self._zi = np.zeros((self._sos.shape[0], 2))

    def process(self, audio: np.ndarray) -> np.ndarray:
        audio = np.asarray(audio, dtype=np.float64)
        if audio.size == 0:
            return audio
        filtered, self._zi = sosfilt(self._sos, audio, zi=self._zi)
        return filtered


class Squelch:
    """Noise gate on raw discriminator output. `envelope()` returns a
    per-sample gain in [0, 1] for the caller to multiply onto whatever audio
    it wants gated (kept separate from filtering audio so the noise-band
    analysis always runs on the unfiltered signal -- band-limiting first
    would remove the very energy the gate looks at).

    Chunk-granular (matches `DevicePipeline.process()`'s ~50 ms chunks at
    the 1.2 MS/s capture rate), with a hang time so a brief fade doesn't
    chatter the gate and a short crossfade at each transition so it doesn't
    click.
    """

    def __init__(
        self,
        sample_rate_hz: float = BIN_RATE_HZ,
        noise_band_hz: float = SQUELCH_NOISE_BAND_HZ,
        threshold: float = SQUELCH_DEFAULT_THRESHOLD,
        hang_time_s: float = SQUELCH_HANG_TIME_S,
        fade_s: float = SQUELCH_FADE_S,
        order: int = SQUELCH_ORDER,
    ):
        self._sos = butter(order, noise_band_hz, btype="highpass", fs=sample_rate_hz, output="sos")
        self._zi = np.zeros((self._sos.shape[0], 2))
        self._sample_rate_hz = sample_rate_hz
        self._threshold = threshold
        self._hang_time_s = hang_time_s
        self._fade_samples = max(1, int(fade_s * sample_rate_hz))
        # Start closed: safer to open on the first chunk that actually
        # proves quiet than to pass a burst of noise before the gate has
        # made its first decision.
        self._open = False
        self._hang_remaining_s = 0.0
        self._prev_gain = 0.0

    def reset(self) -> None:
        self._zi = np.zeros((self._sos.shape[0], 2))
        self._open = False
        self._hang_remaining_s = 0.0
        self._prev_gain = 0.0

    def envelope(self, audio: np.ndarray) -> np.ndarray:
        audio = np.asarray(audio, dtype=np.float64)
        n = audio.size
        if n == 0:
            return audio

        noise, self._zi = sosfilt(self._sos, audio, zi=self._zi)
        noise_rms = float(np.sqrt(np.mean(noise**2)))
        quiet = noise_rms < self._threshold

        if quiet:
            self._open = True
            self._hang_remaining_s = self._hang_time_s
        else:
            self._hang_remaining_s -= n / self._sample_rate_hz
            if self._hang_remaining_s <= 0.0:
                self._open = False

        target_gain = 1.0 if self._open else 0.0
        if target_gain == self._prev_gain:
            gain = np.full(n, target_gain)
        else:
            ramp_len = min(self._fade_samples, n)
            ramp = np.linspace(self._prev_gain, target_gain, ramp_len)
            gain = np.concatenate([ramp, np.full(n - ramp_len, target_gain)]) if ramp_len < n else ramp
        self._prev_gain = target_gain
        return gain
