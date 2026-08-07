from sdr_rx.channels import (
    LO_HZ,
    NUM_BINS,
    all_bins,
    bin_frequency_hz,
    bin_index_for_frequency,
    nwr_bins,
)


def test_all_bins_covers_full_grid():
    bins = all_bins()
    assert len(bins) == NUM_BINS
    assert [b.k for b in bins] == list(range(-24, 24))


def test_nwr_bins_are_the_seven_weather_channels():
    bins = nwr_bins()
    assert [b.channel for b in bins] == ["WX1", "WX2", "WX3", "WX4", "WX5", "WX6", "WX7"]
    freqs = [b.frequency_hz for b in bins]
    assert freqs == [162_400_000.0, 162_425_000.0, 162_450_000.0, 162_475_000.0, 162_500_000.0, 162_525_000.0, 162_550_000.0]


def test_bin_frequency_and_index_round_trip():
    for k in range(-24, 24):
        freq = bin_frequency_hz(k)
        assert bin_index_for_frequency(freq) == k


def test_lo_sits_on_a_bin_edge_not_a_channel_center():
    # The LO must not coincide with any NWR channel's exact center.
    assert LO_HZ not in [b.frequency_hz for b in nwr_bins()]
