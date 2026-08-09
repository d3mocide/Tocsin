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


# Noise-detection band for the squelch: FM discriminator noise power rises
# with frequency (the classic "noise triangle"), while real NWR voice/tone
# content stays under ~3 kHz. Energy above 8 kHz is therefore a good proxy
# for "no signal captured" even though the raw discriminator has no SNR
# estimate of its own. Kept from this module's first version (validated both
# synthetically and against this channelizer's real DC-block/PFB/discriminator
# chain, see test_audio_conditioning.py) rather than the narrower 4-6 kHz
# band the reference implementation below uses for its own, differently
# configured demodulator -- a highpass over more of the available noise-only
# spectrum gives a lower-variance power estimate for this system specifically.
SQUELCH_NOISE_BAND_HZ = 8_000.0
SQUELCH_ORDER = 4

# Everything below is a port of d3mocide/op25-downstream's
# squelch_core.NoiseSquelch (op25/gr-op25_repeater/apps/squelch_core.py),
# itself crediting Pieter-Tjerk de Boer, PA3FWM, "Squelch algorithms"
# (https://www.pa3fwm.nl/technotes/tn16e.html). That implementation is for a
# GNU Radio NBFM chain with a configurable deviation/IF filter and includes
# an optional DB1NV dual-band speech detector; this port drops both --
# Tocsin's discriminator output is already `np.angle()`, unit-gain radians
# per sample, so the original's `disc_gain` normalization has nothing to do
# here, and there's no P25/DMR "voice vs. data" distinction to make on a
# feed that's already split from the raw SAME-decode topic (pipeline.py).
# What's kept is the part that actually solves this module's original
# problem (a single fixed threshold with no universal value, requiring
# per-site tuning): a self-calibrating no-carrier reference and dB-relative
# thresholds, plus the 4-state hysteresis machine that avoids the chatter a
# single threshold falls into at the boundary.
SQUELCH_OPEN_DB = 8.0
SQUELCH_HYST_DB = 3.0
SQUELCH_REHOLD_MARGIN_DB = 1.5
SQUELCH_HANG_MS = 250.0
SQUELCH_ATTACK_MS = 30.0
SQUELCH_RAMP_MS = 8.0
SQUELCH_FRAME_MS = 2.0
SQUELCH_POWER_TAU_MS = 20.0
SQUELCH_REF_TAU_MS = 200.0
# No-carrier reference starting point: measured by feeding AWGN through this
# channelizer's real DC-block/PFB/discriminator chain end to end (not an
# idealized approximation -- see test_audio_conditioning.py), which gives
# ~0.62 rad^2 in the 8 kHz+ band, consistent across all seven NWR bins.
# Deliberately set well below that: the reference tracker only ever rises
# (`_track_reference` -- measured power above the current reference is
# proof the reference was too low, whatever the gate is doing), so an
# under-estimate just means quieting reads low and the gate errs toward
# staying closed until the first ~200 ms of real no-carrier noise calibrates
# it -- never the reverse.
SQUELCH_REF_POWER_INIT = 0.05

_ST_CLOSED = 0
_ST_OPENING = 1  # quieting seen, waiting out the attack delay
_ST_OPEN = 2
_ST_HANG = 3  # quieting lost, waiting out the hang delay


class Squelch:
    """Self-calibrating noise-quieting squelch (see the module-level
    citation above). `envelope()` returns a per-sample gain in [0, 1] for
    the caller to multiply onto whatever audio it wants gated -- kept
    separate from filtering so the noise-band analysis always runs on the
    unfiltered signal passed in here, never the band-limited one
    (`VoiceBandFilter` would have already removed the very energy this
    looks at).

    All decisions are made on quieting: how far the noise-band power has
    fallen below a runtime-tracked no-carrier reference --

        quieting_db = 10 * log10(reference / measured_noise_power)

    -- so `open_db`/`hyst_db` are portable defaults, not per-site numbers:
    the same 8 dB-of-quieting threshold that opens the gate works whether
    the actual noise floor is high or low, because the reference adapts to
    it. Decisions are made on fixed-duration frames (`frame_ms`,
    independent of whatever chunk size the caller passes to `envelope()` --
    partial frames are accumulated across calls) with a short crossfade at
    each gate transition so it doesn't click.
    """

    def __init__(
        self,
        sample_rate_hz: float = BIN_RATE_HZ,
        noise_band_hz: float = SQUELCH_NOISE_BAND_HZ,
        order: int = SQUELCH_ORDER,
        open_db: float = SQUELCH_OPEN_DB,
        hyst_db: float = SQUELCH_HYST_DB,
        rehold_margin_db: float = SQUELCH_REHOLD_MARGIN_DB,
        hang_ms: float = SQUELCH_HANG_MS,
        attack_ms: float = SQUELCH_ATTACK_MS,
        ramp_ms: float = SQUELCH_RAMP_MS,
        frame_ms: float = SQUELCH_FRAME_MS,
        power_tau_ms: float = SQUELCH_POWER_TAU_MS,
        ref_tau_ms: float = SQUELCH_REF_TAU_MS,
        reference: float = 0.0,
    ):
        self._sample_rate_hz = sample_rate_hz
        self._sos = butter(order, noise_band_hz, btype="highpass", fs=sample_rate_hz, output="sos")

        self.open_db = open_db
        self.close_db = open_db - hyst_db
        self.rehold_db = self.close_db + rehold_margin_db

        self.frame_len = max(8, int(round(sample_rate_hz * frame_ms * 1e-3)))
        self.attack_frames = max(1, int(round(attack_ms / frame_ms)))
        self.hang_frames = max(1, int(round(hang_ms / frame_ms)))
        self.ramp_step = 1.0 / max(1.0, ramp_ms * 1e-3 * sample_rate_hz)
        self.power_alpha = 1.0 - np.exp(-frame_ms / power_tau_ms)
        self.ref_alpha = 1.0 - np.exp(-frame_ms / ref_tau_ms)

        # An explicit fixed reference (> 0) skips runtime calibration
        # entirely -- useful if a site's true no-carrier level has already
        # been measured and a fixed value is preferred over letting it drift.
        self._ref_fixed = reference > 0.0
        self._ref_init = reference if self._ref_fixed else SQUELCH_REF_POWER_INIT

        self.reset()

    def reset(self) -> None:
        self._zi = np.zeros((self._sos.shape[0], 2))
        self.state = _ST_CLOSED
        self._state_frames = 0
        self.noise_power = self._ref_init
        # First real measurement snaps `noise_power` directly rather than
        # smoothing in from `_ref_init` -- that seed is deliberately far
        # below the true no-carrier floor (see SQUELCH_REF_POWER_INIT), and
        # smoothing a strong carrier's genuinely low noise-band power in
        # from there would needlessly delay the very first open decision by
        # several POWER_TAU_MS windows for no benefit; every frame after the
        # first is smoothed normally.
        self._noise_power_seeded = False
        self.reference = self._ref_init
        self._gate_target = 0.0
        self._envelope_level = 0.0
        self._acc_sum = 0.0
        self._acc_n = 0

    def is_open(self) -> bool:
        return self.state in (_ST_OPEN, _ST_HANG)

    def quieting_db(self) -> float:
        return 10.0 * np.log10(self.reference / max(self.noise_power, 1e-12))

    def _track_reference(self) -> None:
        if not self._ref_fixed and self.noise_power > self.reference:
            self.reference += (self.noise_power - self.reference) * self.ref_alpha

    def _frame_decision(self) -> None:
        """Advance the squelch state machine by one frame."""
        q = self.quieting_db()
        carrier_open = q >= self.open_db
        carrier_hold = q >= self.close_db
        carrier_rehold = q >= self.rehold_db

        prev = self.state
        self._state_frames += 1
        self._track_reference()

        if self.state == _ST_CLOSED:
            if carrier_open:
                self.state = _ST_OPENING
        elif self.state == _ST_OPENING:
            if not carrier_open:
                self.state = _ST_CLOSED
            elif self._state_frames >= self.attack_frames:
                self.state = _ST_OPEN
        elif self.state == _ST_OPEN:
            if not carrier_hold:
                self.state = _ST_HANG
        elif self.state == _ST_HANG:
            # Returning to OPEN needs more quieting than leaving it did. A
            # signal decaying to exactly close_db would otherwise oscillate
            # OPEN<->HANG on adjacent frames -- and because each transition
            # restarts the hang timer, the squelch could never close at all.
            if carrier_rehold:
                self.state = _ST_OPEN
            elif self._state_frames >= self.hang_frames:
                self.state = _ST_CLOSED

        if self.state != prev:
            self._state_frames = 0
            self._gate_target = 1.0 if self.is_open() else 0.0

    def envelope(self, audio: np.ndarray) -> np.ndarray:
        audio = np.asarray(audio, dtype=np.float64)
        n = audio.size
        if n == 0:
            return audio

        noise, self._zi = sosfilt(self._sos, audio, zi=self._zi)
        noise2 = noise * noise

        env = np.empty(n, dtype=np.float64)
        pos = 0
        while pos < n:
            take = min(n - pos, self.frame_len - self._acc_n)
            seg = slice(pos, pos + take)

            self._acc_sum += float(np.sum(noise2[seg]))
            self._acc_n += take

            level0 = self._envelope_level
            target = self._gate_target
            if level0 == target:
                env[seg] = level0
            else:
                step = self.ramp_step if target > level0 else -self.ramp_step
                ramp = level0 + step * np.arange(1, take + 1, dtype=np.float64)
                np.clip(ramp, min(level0, target), max(level0, target), out=ramp)
                env[seg] = ramp
                self._envelope_level = float(ramp[-1])

            if self._acc_n >= self.frame_len:
                p = self._acc_sum / self._acc_n
                if self._noise_power_seeded:
                    self.noise_power += (p - self.noise_power) * self.power_alpha
                else:
                    self.noise_power = p
                    self._noise_power_seeded = True
                self._acc_sum = 0.0
                self._acc_n = 0
                self._frame_decision()

            pos += take

        return env
