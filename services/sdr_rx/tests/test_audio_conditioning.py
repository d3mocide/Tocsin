import numpy as np
import pytest

from sdr_rx.audio_conditioning import SQUELCH_REF_POWER_INIT, Squelch, VoiceBandFilter
from sdr_rx.channelizer import PolyphaseChannelizer
from sdr_rx.channels import nwr_bins
from sdr_rx.dc_block import DCBlocker
from sdr_rx.discriminator import FMDiscriminator
from sdr_rx.resample import BIN_RATE_HZ

FS = 50_000.0
FS_IQ = 1_200_000.0


def _tone(freq_hz, n, fs=FS, amplitude=1.0):
    t = np.arange(n) / fs
    return amplitude * np.sin(2 * np.pi * freq_hz * t)


class TestVoiceBandFilter:
    def test_in_band_tone_passes_near_unity_gain(self):
        f = VoiceBandFilter()
        n = 20_000
        y = f.process(_tone(800.0, n))
        steady = y[n // 2 :]
        amplitude = np.sqrt(2) * np.sqrt(np.mean(steady**2))
        assert amplitude > 0.9

    def test_out_of_band_tone_is_heavily_attenuated(self):
        f = VoiceBandFilter()
        n = 20_000
        y = f.process(_tone(8_000.0, n))
        steady = y[n // 2 :]
        amplitude = np.sqrt(2) * np.sqrt(np.mean(steady**2))
        assert amplitude < 0.05

    def test_state_carries_across_chunked_calls(self):
        whole = VoiceBandFilter()
        chunked = VoiceBandFilter()
        rng = np.random.default_rng(0)
        x = rng.normal(size=10_000)

        y_whole = whole.process(x)
        y_chunked = np.concatenate([chunked.process(x[i : i + 333]) for i in range(0, len(x), 333)])

        np.testing.assert_allclose(y_whole, y_chunked, atol=1e-10)

    def test_empty_input_returns_empty(self):
        f = VoiceBandFilter()
        assert f.process(np.zeros(0)).size == 0


def _noise(n, rng):
    """Stand-in for a genuinely no-carrier discriminator output: full-scale,
    uniform-phase noise (matches what an FM discriminator produces with only
    thermal/receiver noise at its input -- validated against this
    channelizer's real DC-block/PFB/discriminator chain fed AWGN, see
    test_calibration_matches_the_real_channelizer_chain below)."""
    return rng.uniform(-np.pi, np.pi, n)


class TestSquelch:
    def test_no_carrier_gate_stays_closed(self):
        sq = Squelch()
        rng = np.random.default_rng(1)
        # Long enough to run the reference tracker through several
        # ref_tau_ms windows -- the gate must stay closed even once fully
        # calibrated on nothing but noise, not just at cold start.
        envelope = sq.envelope(_noise(20_000, rng))
        assert not sq.is_open()
        assert np.all(envelope == 0.0)

    def test_strong_carrier_opens_the_gate(self):
        sq = Squelch()
        n = 4_000
        signal = _tone(800.0, n, amplitude=0.6) + 0.02 * np.random.default_rng(2).standard_normal(n)
        envelope = sq.envelope(signal)
        assert sq.is_open()
        assert envelope[-1] == 1.0
        assert envelope[-100:].min() == 1.0  # settled open well before the end of the chunk

    def test_reference_self_calibrates_upward_from_its_conservative_init(self):
        """The whole point of this design over a fixed threshold: the
        no-carrier reference is deliberately under-estimated at
        construction (errs toward closed) and must rise to the true noise
        floor after real exposure to it, with no site-specific tuning."""
        sq = Squelch()
        initial_reference = sq.reference
        rng = np.random.default_rng(4)
        sq.envelope(_noise(20_000, rng))
        assert sq.reference > initial_reference * 2

    def test_gate_stays_open_through_a_brief_dropout_then_closes(self):
        sq = Squelch(hang_ms=50.0, attack_ms=10.0)
        chunk_len = 2_000  # 20 frames at the default 2 ms frame
        rng = np.random.default_rng(3)
        quiet = _tone(800.0, chunk_len, amplitude=0.6)
        noisy = _noise(chunk_len, rng)

        first = sq.envelope(quiet)
        assert first[-1] == 1.0
        assert sq.is_open()

        # Dropout starts: hang_frames=25, only ~19 elapse in this chunk --
        # still bridged (audio keeps playing through the gap).
        second = sq.envelope(noisy)
        assert np.all(second == 1.0)
        assert sq.is_open()

        # More noise pushes the cumulative dropout past the hang window --
        # the gate closes partway through, with a ramp, not a click.
        third = sq.envelope(noisy)
        assert third[0] == 1.0
        assert third[-1] == 0.0
        assert np.any((third > 0.0) & (third < 1.0))
        assert not sq.is_open()

    def test_threshold_jitter_does_not_thrash_open_and_hang(self):
        """Port of op25-downstream's own regression test for this exact
        failure mode: a signal sitting near the closing threshold must not
        oscillate OPEN<->HANG forever (each transition would otherwise
        reset the hang timer, so the squelch could never actually close).
        Drives the state machine directly, the same way the reference
        implementation's own test does, since synthesizing audio that lands
        on an exact dB value is indirect and fragile."""
        sq = Squelch()
        rng = np.random.default_rng(5)
        sq.envelope(_tone(800.0, 4_000, amplitude=0.6))  # open on a solid signal
        assert sq.is_open()

        transitions = 0
        prev_state = sq.state
        for _ in range(int(10.0 * FS / sq.frame_len)):  # ~10s worth of frames
            jitter_db = rng.uniform(-0.4, 0.4)
            sq.noise_power = sq.reference / (10.0 ** ((sq.close_db + jitter_db) / 10.0))
            sq._frame_decision()
            if sq.state != prev_state:
                transitions += 1
                prev_state = sq.state
        assert transitions <= 4
        assert not sq.is_open()  # jittering across the line still ends up closed

    def test_state_carries_across_chunked_calls(self):
        whole = Squelch()
        chunked = Squelch()
        rng = np.random.default_rng(6)
        signal = np.concatenate([_noise(3_000, rng), _tone(800.0, 6_000, amplitude=0.6), _noise(3_000, rng)])

        y_whole = whole.envelope(signal)
        y_chunked = np.concatenate([chunked.envelope(signal[i : i + 250]) for i in range(0, len(signal), 250)])

        np.testing.assert_allclose(y_whole, y_chunked, atol=1e-10)

    def test_empty_input_returns_empty(self):
        sq = Squelch()
        assert sq.envelope(np.zeros(0)).size == 0

    def test_squelch_opens_on_a_real_signal_through_the_actual_channelizer_chain(self):
        """End-to-end validation against this system's real DC-block/PFB/
        discriminator chain (not the synthetic uniform-phase noise stand-in
        used above), the same rigor op25-downstream's own squelch test suite
        applies -- SQUELCH_REF_POWER_INIT and the noise band were both
        calibrated this way, not guessed. AWGN alone must never open the
        gate; a clean FM-modulated carrier at the same channel must."""
        rng = np.random.default_rng(9)
        wx5 = next(b for b in nwr_bins() if b.channel == "WX5")
        baseband_offset_hz = (wx5.k + 0.5) * 25_000.0
        n = int(0.75 * FS_IQ)  # 750ms is plenty for the reference to settle; keeps the full-chain test fast
        t = np.arange(n) / FS_IQ

        def run(iq):
            spectrum = PolyphaseChannelizer().process(DCBlocker().process(iq))
            audio = FMDiscriminator().process(spectrum[:, wx5.k % 48])
            sq = Squelch()
            sq.envelope(audio)
            return sq

        noise_only = 0.1 * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
        assert not run(noise_only).is_open()

        freq = baseband_offset_hz + 300.0 * np.sin(2 * np.pi * 3.0 * t)
        phase = 2 * np.pi * np.cumsum(freq) / FS_IQ
        carrier = np.exp(1j * phase) + 0.02 * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
        assert run(carrier).is_open()

    def test_ref_power_init_is_conservative_relative_to_the_real_measured_floor(self):
        """SQUELCH_REF_POWER_INIT must under-estimate the real no-carrier
        noise floor (see its own docstring: errs toward closed at cold
        start, then the rise-only tracker calibrates up) -- measured against
        the real channelizer chain, not the idealized synthetic noise used
        elsewhere in this file."""
        rng = np.random.default_rng(11)
        wx5 = next(b for b in nwr_bins() if b.channel == "WX5")
        n = int(0.75 * FS_IQ)
        noise = 0.1 * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
        spectrum = PolyphaseChannelizer().process(DCBlocker().process(noise))
        audio = FMDiscriminator().process(spectrum[:, wx5.k % 48])

        sq = Squelch()
        sq.envelope(audio)
        # sq.reference has now calibrated up to (approximately) the true
        # floor; the constant it started from must have been well below it.
        assert SQUELCH_REF_POWER_INIT < sq.reference / 4


class TestPrecisionAndSpans:
    """`envelope()` describes the gain envelope as merged constant spans plus
    the occasional ramp rather than writing it frame by frame (see its
    comments). These pin the two things that rewrite could have broken:
    the spans have to reconstruct the same envelope the direct
    frame-by-frame form produces, and precision has to follow the input the
    way it does through the rest of the chain."""

    @staticmethod
    def _reference_envelope(sq, audio):
        """The direct form: one segment at a time, no span merging, ramps
        materialized per segment. Deliberately a transcription of the shape
        `envelope()` used to have, so it is an independent check on the
        span construction rather than the same code twice."""
        from scipy.signal import sosfilt

        noise, sq._zi = sosfilt(sq._sos, audio, zi=sq._zi)
        noise2 = noise * noise
        n = audio.size
        env = np.empty(n, dtype=np.float64)
        pos = 0
        while pos < n:
            take = min(n - pos, sq.frame_len - sq._acc_n)
            seg = slice(pos, pos + take)
            sq._acc_sum += float(np.sum(noise2[seg]))
            sq._acc_n += take
            level0, target = sq._envelope_level, sq._gate_target
            if level0 == target:
                env[seg] = level0
            else:
                step = sq.ramp_step if target > level0 else -sq.ramp_step
                ramp = level0 + step * np.arange(1, take + 1, dtype=np.float64)
                np.clip(ramp, min(level0, target), max(level0, target), out=ramp)
                env[seg] = ramp
                sq._envelope_level = float(ramp[-1])
            if sq._acc_n >= sq.frame_len:
                p = sq._acc_sum / sq._acc_n
                if sq._noise_power_seeded:
                    sq.noise_power += (p - sq.noise_power) * sq.power_alpha
                else:
                    sq.noise_power, sq._noise_power_seeded = p, True
                sq._acc_sum, sq._acc_n = 0.0, 0
                sq._frame_decision()
            pos += take
        return env

    @staticmethod
    def _gated_signal(rng):
        """Alternating broadband noise and a quiet in-band tone, so the run
        crosses closed/opening/open/hang in both directions and every ramp
        gets exercised -- a steady signal would never leave a constant span
        and would prove nothing about the merging."""
        parts = []
        for i in range(6):
            t = np.arange(25_000) / BIN_RATE_HZ
            parts.append(0.3 * np.sin(2 * np.pi * 1000.0 * t) if i % 2 else rng.standard_normal(25_000))
        return np.concatenate(parts)

    def test_span_construction_matches_the_direct_frame_by_frame_form(self):
        signal = self._gated_signal(np.random.default_rng(3))
        # Chunk sizes that share no factor with frame_len (100), so frames
        # straddle chunk boundaries in every alignment.
        chunks = [777, 2731, 13, 4096, 2731]

        fast, reference = Squelch(), Squelch()
        got, want, pos, i = [], [], 0, 0
        while pos < signal.size:
            block = signal[pos : pos + chunks[i % len(chunks)]]
            got.append(fast.envelope(block))
            want.append(self._reference_envelope(reference, block))
            pos += block.size
            i += 1

        np.testing.assert_array_equal(np.concatenate(got), np.concatenate(want))
        assert fast.state == reference.state

    def test_gate_actually_opens_and_closes_in_that_signal(self):
        """Guards the test above from silently becoming vacuous: if the
        signal stopped driving transitions, comparing two all-ones
        envelopes would still pass."""
        sq = Squelch()
        env = sq.envelope(self._gated_signal(np.random.default_rng(3)))
        assert (env > 0.99).any() and (env < 0.01).any()
        assert 0.0 < np.mean((env > 0.0) & (env < 1.0)) < 0.05  # brief ramps, not a slow drift

    @pytest.mark.parametrize("dtype", [np.float32, np.float64])
    def test_precision_follows_the_input(self, dtype):
        audio = np.random.default_rng(0).standard_normal(5_000).astype(dtype)
        assert Squelch().envelope(audio).dtype == dtype
        assert VoiceBandFilter().process(audio).dtype == dtype

    def test_float32_gate_decisions_match_float64(self):
        signal = self._gated_signal(np.random.default_rng(3))
        wide = Squelch().envelope(signal)
        narrow = Squelch().envelope(signal.astype(np.float32))
        np.testing.assert_allclose(narrow, wide, atol=1e-4)
