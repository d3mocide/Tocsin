import numpy as np

from sdr_rx.audio_conditioning import Squelch, VoiceBandFilter

FS = 50_000.0


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


class TestSquelch:
    def test_noise_only_signal_is_squelched_from_the_start(self):
        sq = Squelch()
        rng = np.random.default_rng(1)
        noise = rng.uniform(-np.pi, np.pi, 4_000)
        envelope = sq.envelope(noise)
        assert np.all(envelope == 0.0)

    def test_strong_carrier_opens_the_gate(self):
        sq = Squelch()
        n = 4_000
        signal = _tone(800.0, n, amplitude=0.6) + 0.02 * np.random.default_rng(2).standard_normal(n)
        envelope = sq.envelope(signal)
        assert envelope[-1] == 1.0
        assert envelope[-100:].min() == 1.0  # settled open well before the end of the chunk

    def test_gate_stays_open_through_hang_time_then_closes(self):
        sq = Squelch(hang_time_s=0.05, fade_s=0.002)
        chunk_len = 2_000  # 0.04s at FS
        rng = np.random.default_rng(3)
        quiet = _tone(800.0, chunk_len, amplitude=0.6)
        noisy = rng.uniform(-np.pi, np.pi, chunk_len)

        first = sq.envelope(quiet)
        assert first[-1] == 1.0

        # hang_remaining 0.05s, first noisy chunk consumes 0.04s of it -- still open
        second = sq.envelope(noisy)
        assert np.all(second == 1.0)

        # a second noisy chunk exceeds the hang time -- gate closes, with a ramp
        third = sq.envelope(noisy)
        assert third[0] == 1.0
        assert third[-1] == 0.0
        assert np.any((third > 0.0) & (third < 1.0))  # a real ramp, not an instant jump

    def test_state_carries_across_chunked_calls(self):
        whole = Squelch()
        chunked = Squelch()
        n = _tone(800.0, 6_000, amplitude=0.6)

        y_whole = whole.envelope(n)
        y_chunked = np.concatenate([chunked.envelope(n[i : i + 250]) for i in range(0, len(n), 250)])

        np.testing.assert_allclose(y_whole, y_chunked, atol=1e-10)

    def test_empty_input_returns_empty(self):
        sq = Squelch()
        assert sq.envelope(np.zeros(0)).size == 0
