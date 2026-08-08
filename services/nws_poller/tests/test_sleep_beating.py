from nws_poller import HEARTBEAT_SLICE_SECONDS, _sleep_beating


class FakeHeartbeat:
    """Mirrors the real `Heartbeat.beat()`'s self-throttling: it is called
    unconditionally and decides for itself when to write."""

    def __init__(self, interval_seconds=10.0):
        self.interval = interval_seconds
        self.calls = []
        self.writes = 0
        self._elapsed = 0.0

    def beat(self, **detail):
        self.calls.append(detail)


def test_beats_several_times_across_one_poll_interval():
    """The heartbeat key's TTL is 30s and the default poll interval is 60s,
    so beating once per poll left it expired for half of every cycle --
    the status board flapped a healthy poller to "no heartbeat"."""
    heartbeat = FakeHeartbeat()
    slept = []

    _sleep_beating(60.0, heartbeat, sleep=slept.append, areas=["OR"])

    assert sum(slept) == 60.0
    assert max(slept) <= HEARTBEAT_SLICE_SECONDS
    assert len(heartbeat.calls) == 13  # one per 5s slice, plus the beat that ends the wait
    assert heartbeat.calls[0] == {"areas": ["OR"]}


def test_tolerates_no_redis_configured():
    slept = []
    _sleep_beating(10.0, None, sleep=slept.append)
    assert sum(slept) == 10.0
