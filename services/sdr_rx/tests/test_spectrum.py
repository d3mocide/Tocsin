import numpy as np

from sdr_rx.channels import NUM_BINS, all_bins
from sdr_rx.spectrum import LoggingSpectrumSink, SpectrumTracker


def _flat_spectrum(n_frames=4, num_bins=NUM_BINS, magnitude=1.0):
    return np.full((n_frames, num_bins), magnitude, dtype=complex)


def test_sample_publishes_a_snapshot_with_every_bin():
    sink = LoggingSpectrumSink()
    tracker = SpectrumTracker("home", sink=sink, now_fn=lambda: 0.0)

    tracker.sample(_flat_spectrum())

    assert len(sink.history) == 1
    snapshot = sink.history[0]
    assert snapshot.site == "home"
    assert len(snapshot.bin_frequencies_hz) == NUM_BINS
    assert len(snapshot.bin_power_db) == NUM_BINS
    assert snapshot.bin_frequencies_hz == tuple(b.frequency_hz for b in all_bins())


def test_first_sample_always_publishes_regardless_of_clock_start():
    # SpectrumTracker._last_published starts as None, not 0.0 -- a
    # monotonic clock that doesn't start at 0 must not delay the first
    # publish (a bug a `0.0` sentinel would have introduced).
    sink = LoggingSpectrumSink()
    tracker = SpectrumTracker("home", sink=sink, now_fn=lambda: 1_000_000.0)
    tracker.sample(_flat_spectrum())
    assert len(sink.history) == 1


def test_publish_is_throttled_to_the_configured_interval():
    sink = LoggingSpectrumSink()
    clock = {"t": 0.0}
    tracker = SpectrumTracker("home", sink=sink, publish_interval_seconds=1.0, now_fn=lambda: clock["t"])

    tracker.sample(_flat_spectrum())
    clock["t"] = 0.5
    tracker.sample(_flat_spectrum())  # too soon, should be skipped
    clock["t"] = 1.5
    tracker.sample(_flat_spectrum())

    assert len(sink.history) == 2


def test_bin_power_is_indexed_by_k_not_raw_fft_column():
    """A tone concentrated in raw FFT column 0 (k=-24 in odd-stacked
    indexing, per DevicePipeline's own `k % NUM_BINS` mapping) must show
    up at k=-24's position in the snapshot, not at index 0 of
    `all_bins()`'s k=-24..23 ordering coincidentally lining up -- this
    test picks a column where the naive (unmapped) and correct orderings
    would disagree if the mapping were wrong."""
    sink = LoggingSpectrumSink()
    tracker = SpectrumTracker("home", sink=sink, now_fn=lambda: 0.0)

    spectrum = np.full((4, NUM_BINS), 1e-6, dtype=complex)
    loud_column = 5  # raw FFT column 5 -> k = 5 (since 5 % 48 == 5)
    spectrum[:, loud_column] = 10.0
    tracker.sample(spectrum)

    snapshot = sink.history[0]
    bins = all_bins()
    loud_bin_index = next(i for i, b in enumerate(bins) if b.k == loud_column)
    assert snapshot.bin_power_db[loud_bin_index] > max(
        p for i, p in enumerate(snapshot.bin_power_db) if i != loud_bin_index
    )


def test_negative_k_wraps_correctly_to_its_raw_fft_column():
    """k=-24 wraps to raw FFT column 24 (`-24 % 48 == 24`) -- the case
    that would actually break if bin ordering were assumed sequential
    instead of using DevicePipeline's own `k % NUM_BINS` mapping."""
    sink = LoggingSpectrumSink()
    tracker = SpectrumTracker("home", sink=sink, now_fn=lambda: 0.0)

    spectrum = np.full((4, NUM_BINS), 1e-6, dtype=complex)
    spectrum[:, 24] = 10.0  # -24 % 48 == 24
    tracker.sample(spectrum)

    snapshot = sink.history[0]
    bins = all_bins()
    k_minus_24_index = next(i for i, b in enumerate(bins) if b.k == -24)
    assert snapshot.bin_power_db[k_minus_24_index] > max(
        p for i, p in enumerate(snapshot.bin_power_db) if i != k_minus_24_index
    )
