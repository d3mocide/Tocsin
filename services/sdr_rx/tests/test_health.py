import numpy as np
import pytest

from sdr_rx.health import HealthTracker, LoggingHealthSink


def test_sample_computes_rms_and_power():
    tracker = HealthTracker()
    audio = np.array([1.0, -1.0, 1.0, -1.0])
    health = tracker.sample("WX1", audio, now=0.0)
    assert health.rms == pytest.approx(1.0)
    assert health.power == pytest.approx(1.0)
    assert not health.dead


def test_empty_sample_is_silence_not_a_crash():
    tracker = HealthTracker()
    health = tracker.sample("WX1", np.array([]), now=0.0)
    assert health.rms == 0.0
    assert health.power == 0.0


def test_flags_dead_after_flat_carrier_window():
    tracker = HealthTracker(flat_carrier_seconds=30.0, rms_threshold=1e-4)
    silence = np.zeros(10)
    tracker.sample("WX1", silence, now=0.0)
    still_flat = tracker.sample("WX1", silence, now=29.0)
    assert not still_flat.dead
    now_dead = tracker.sample("WX1", silence, now=30.0)
    assert now_dead.dead


def test_recovers_after_signal_returns():
    tracker = HealthTracker(flat_carrier_seconds=30.0)
    tracker.sample("WX1", np.zeros(10), now=0.0)
    tracker.sample("WX1", np.zeros(10), now=40.0)
    recovered = tracker.sample("WX1", np.ones(10), now=41.0)
    assert not recovered.dead
    # and the flat-carrier clock restarts rather than staying tripped
    still_alive = tracker.sample("WX1", np.zeros(10), now=41.0 + 29.0)
    assert not still_alive.dead


def test_sink_records_every_sample():
    sink = LoggingHealthSink()
    tracker = HealthTracker(sink=sink)
    tracker.sample("WX1", np.ones(5), now=0.0)
    tracker.sample("WX2", np.ones(5), now=0.0)
    assert len(sink.history) == 2


def test_channels_tracked_independently():
    tracker = HealthTracker(flat_carrier_seconds=30.0)
    tracker.sample("WX1", np.zeros(10), now=0.0)
    tracker.sample("WX2", np.ones(10), now=0.0)
    wx1 = tracker.sample("WX1", np.zeros(10), now=30.0)
    wx2 = tracker.sample("WX2", np.ones(10), now=30.0)
    assert wx1.dead
    assert not wx2.dead
