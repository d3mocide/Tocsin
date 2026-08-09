import numpy as np
import pytest

from sdr_rx.health import HealthTracker, LoggingHealthSink


def test_sample_computes_rms_and_power():
    tracker = HealthTracker()
    audio = np.array([1.0, -1.0, 1.0, -1.0])
    health = tracker.sample("home", "WX1", audio, now=0.0)
    assert health.site == "home"
    assert health.rms == pytest.approx(1.0)
    assert health.power == pytest.approx(1.0)
    assert not health.dead


def test_empty_sample_is_silence_not_a_crash():
    tracker = HealthTracker()
    health = tracker.sample("home", "WX1", np.array([]), now=0.0)
    assert health.rms == 0.0
    assert health.power == 0.0


def test_flags_dead_after_flat_carrier_window():
    tracker = HealthTracker(flat_carrier_seconds=30.0, rms_threshold=1e-4)
    silence = np.zeros(10)
    tracker.sample("home", "WX1", silence, now=0.0)
    still_flat = tracker.sample("home", "WX1", silence, now=29.0)
    assert not still_flat.dead
    now_dead = tracker.sample("home", "WX1", silence, now=30.0)
    assert now_dead.dead


def test_recovers_after_signal_returns():
    tracker = HealthTracker(flat_carrier_seconds=30.0)
    tracker.sample("home", "WX1", np.zeros(10), now=0.0)
    tracker.sample("home", "WX1", np.zeros(10), now=40.0)
    recovered = tracker.sample("home", "WX1", np.ones(10), now=41.0)
    assert not recovered.dead
    # and the flat-carrier clock restarts rather than staying tripped
    still_alive = tracker.sample("home", "WX1", np.zeros(10), now=41.0 + 29.0)
    assert not still_alive.dead


def test_sink_records_every_sample():
    sink = LoggingHealthSink()
    tracker = HealthTracker(sink=sink)
    tracker.sample("home", "WX1", np.ones(5), now=0.0)
    tracker.sample("home", "WX2", np.ones(5), now=0.0)
    assert len(sink.history) == 2


def test_sink_reports_are_throttled_but_dead_detection_is_not():
    """Regression test for the fix in docs/design/tracking.md's 2026-08-09
    entry: `sample()` must still update flat-carrier state on every call
    (dead detection stays exactly as timely), but the sink -- the expensive
    part, a Redis round trip -- should only be hit at most once per
    `report_interval_s` per channel."""
    sink = LoggingHealthSink()
    tracker = HealthTracker(sink=sink, flat_carrier_seconds=30.0, rms_threshold=1e-4, report_interval_s=1.0)

    tracker.sample("home", "WX1", np.zeros(10), now=0.0)  # first-ever sample always reports
    tracker.sample("home", "WX1", np.zeros(10), now=0.2)  # within the throttle window
    tracker.sample("home", "WX1", np.zeros(10), now=0.9)  # still within it
    assert len(sink.history) == 1

    tracker.sample("home", "WX1", np.zeros(10), now=1.1)  # past the throttle window
    assert len(sink.history) == 2

    # Dead detection must not lag behind the throttled reports: feed a
    # sample every 0.9s (well under the 1s report interval) and confirm
    # `dead` still flips at the documented 30s flat-carrier boundary.
    tracker2 = HealthTracker(sink=LoggingHealthSink(), flat_carrier_seconds=30.0, rms_threshold=1e-4)
    t = 0.0
    result = None
    while t <= 31.0:
        result = tracker2.sample("home", "WX2", np.zeros(10), now=t)
        t += 0.9
    assert result.dead


def test_report_throttling_is_independent_per_channel():
    sink = LoggingHealthSink()
    tracker = HealthTracker(sink=sink, report_interval_s=1.0)
    tracker.sample("home", "WX1", np.ones(5), now=0.0)
    tracker.sample("home", "WX2", np.ones(5), now=0.0)
    tracker.sample("home", "WX1", np.ones(5), now=0.5)  # throttled
    tracker.sample("home", "WX2", np.ones(5), now=0.5)  # throttled
    assert len(sink.history) == 2


def test_channels_tracked_independently():
    tracker = HealthTracker(flat_carrier_seconds=30.0)
    tracker.sample("home", "WX1", np.zeros(10), now=0.0)
    tracker.sample("home", "WX2", np.ones(10), now=0.0)
    wx1 = tracker.sample("home", "WX1", np.zeros(10), now=30.0)
    wx2 = tracker.sample("home", "WX2", np.ones(10), now=30.0)
    assert wx1.dead
    assert not wx2.dead


def test_same_channel_name_at_different_sites_is_tracked_independently():
    """Regression test: a shared HealthTracker across two dongles/sites
    (main()'s actual usage) used to key only on channel, so two sites'
    WX5 would collide in _flat_since and in every emitted ChannelHealth --
    the same bug class already fixed once for sdr_rx.bus's ZMQ topics
    (docs/design/tracking.md, 2026-08-07)."""
    tracker = HealthTracker(flat_carrier_seconds=30.0)
    tracker.sample("home", "WX5", np.zeros(10), now=0.0)  # home/WX5 goes flat
    tracker.sample("office", "WX5", np.ones(10), now=0.0)  # office/WX5 stays alive

    home = tracker.sample("home", "WX5", np.zeros(10), now=30.0)
    office = tracker.sample("office", "WX5", np.ones(10), now=30.0)

    assert home.site == "home"
    assert home.dead
    assert office.site == "office"
    assert not office.dead
