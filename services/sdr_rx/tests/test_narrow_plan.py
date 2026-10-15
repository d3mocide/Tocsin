"""The weather-only plan (12 bins at 300 kS/s) must give the same per-channel audio as the full 48-bin plan."""
import numpy as np
import pytest

from sdr_rx.channelizer import PolyphaseChannelizer
from sdr_rx.channels import all_bins, nwr_bins, validate_num_bins
from sdr_rx.pipeline import DevicePipeline
from sdr_rx.ring_buffer import ChannelRingBuffer
from sdr_rx.spectrum import SpectrumTracker


class _Publisher:
    def publish(self, topic, site, channel, sample_rate_hz, pcm):
        pass


def _plan(num_bins):
    return PolyphaseChannelizer(num_bins=num_bins, decimation=num_bins // 2), num_bins * 25_000.0


def test_validate_num_bins_accepts_real_rtl_rates_and_rejects_the_rest():
    assert validate_num_bins(12) == 12        # 300 kS/s
    assert validate_num_bins(48) == 48        # 1.2 MS/s
    for bad in (7, 8, 11, 13, 14, 16, 24, 36):  # odd, too small, or inside librtlsdr unsupported gap
        with pytest.raises(ValueError):
            validate_num_bins(bad)


def test_all_bins_for_the_narrow_plan_still_contain_the_seven_weather_channels():
    bins = all_bins(12)
    assert [b.k for b in bins] == list(range(-6, 6))
    assert [b.channel for b in bins if b.channel] == [f"WX{i}" for i in range(1, 8)]
    assert len(nwr_bins()) == 7


@pytest.mark.parametrize("k", [-4, -3, -2, -1, 0, 1, 2])
def test_narrow_plan_tone_on_each_weather_channel_lands_in_its_own_bin(k):
    ch, fs = _plan(12)
    n = 24_000
    tone = np.exp(1j * 2 * np.pi * (k + 0.5) * 25_000.0 * np.arange(n) / fs).astype(np.complex64)
    out = np.concatenate([ch.process(tone[i : i + 4_000]) for i in range(0, n, 4_000)])
    steady = np.abs(out[len(out) // 2 :])
    assert steady[:, k % 12].mean() > 0.9 and steady[:, k % 12].std() < 1e-3
    others = np.delete(steady.mean(axis=0), k % 12)
    assert others.max() < 0.05                  # neighbours are well down


def _recovered_audio(tmp_path, num_bins, k=2, seconds=1.0):
    """FM carrier on weather channel k with a 1 kHz tone (3 kHz deviation), through a full DevicePipeline."""
    channelizer, fs = _plan(num_bins)
    n = int(fs * seconds)
    t = np.arange(n) / fs
    phase = 2 * np.pi * (k + 0.5) * 25_000.0 * t + (3_000.0 / 1_000.0) * (1 - np.cos(2 * np.pi * 1_000.0 * t))
    rings = {b.channel: ChannelRingBuffer(tmp_path / f"{num_bins}", b.channel, window_seconds=2) for b in nwr_bins()}
    pipeline = DevicePipeline("s", _Publisher(), rings, channelizer=channelizer,
                              spectrum=SpectrumTracker("s", num_bins=num_bins))
    iq = np.exp(1j * phase).astype(np.complex64)
    for i in range(0, n, 20_000):
        pipeline.process(iq[i : i + 20_000])
    channel = {b.k: b.channel for b in nwr_bins()}[k]
    return rings[channel].read_last(20_000)


def test_narrow_and_full_plans_recover_the_same_tone_from_the_same_station(tmp_path):
    audio = {n: _recovered_audio(tmp_path, n) for n in (12, 48)}
    assert audio[12].size == audio[48].size
    spec = {n: np.abs(np.fft.rfft(a - a.mean())) for n, a in audio.items()}
    # Same dominant frequency, and comparable level (the plans differ only in how many unused bins they compute).
    assert np.argmax(spec[12]) == np.argmax(spec[48])
    assert spec[12].max() == pytest.approx(spec[48].max(), rel=0.1)


def test_default_spectrum_tracker_follows_the_channelizer_size(tmp_path):
    channelizer, _ = _plan(12)
    rings = {b.channel: ChannelRingBuffer(tmp_path, b.channel, window_seconds=1) for b in nwr_bins()}
    pipeline = DevicePipeline("s", _Publisher(), rings, channelizer=channelizer)
    pipeline.process(np.ones(5_000, dtype=np.complex64))        # must not raise on a 12-column spectrum
