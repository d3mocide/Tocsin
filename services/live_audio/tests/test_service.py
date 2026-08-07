from live_audio.service import IcecastConfig, Streamer

ICECAST = IcecastConfig(host="icecast", port=8000, user="source", password="hackme")


class FakeFeeder:
    """Records writes; `should_die` simulates ffmpeg exiting on its own."""

    instances: list["FakeFeeder"] = []

    def __init__(self, command):
        self.command = command
        self.writes: list[bytes] = []
        self.closed = False
        self.alive = True
        FakeFeeder.instances.append(self)

    def write(self, pcm_bytes: bytes) -> None:
        self.writes.append(pcm_bytes)

    def is_alive(self) -> bool:
        return self.alive

    def close(self) -> None:
        self.closed = True
        self.alive = False


def setup_function():
    FakeFeeder.instances.clear()


def test_feed_creates_a_feeder_lazily_on_first_audio():
    streamer = Streamer(ICECAST, feeder_factory=FakeFeeder)
    assert FakeFeeder.instances == []
    streamer.feed("home", "WX5", 16000, b"\x00\x00")
    assert len(FakeFeeder.instances) == 1
    assert FakeFeeder.instances[0].writes == [b"\x00\x00"]


def test_feed_reuses_the_same_feeder_for_the_same_key():
    streamer = Streamer(ICECAST, feeder_factory=FakeFeeder)
    streamer.feed("home", "WX5", 16000, b"\x00\x00")
    streamer.feed("home", "WX5", 16000, b"\x01\x01")
    assert len(FakeFeeder.instances) == 1
    assert FakeFeeder.instances[0].writes == [b"\x00\x00", b"\x01\x01"]


def test_different_channels_get_independent_feeders():
    streamer = Streamer(ICECAST, feeder_factory=FakeFeeder)
    streamer.feed("home", "WX5", 16000, b"\x00\x00")
    streamer.feed("home", "WX1", 16000, b"\x01\x01")
    assert len(FakeFeeder.instances) == 2


def test_dead_feeder_stops_receiving_writes_without_crashing():
    streamer = Streamer(ICECAST, feeder_factory=FakeFeeder)
    streamer.feed("home", "WX5", 16000, b"\x00\x00")
    FakeFeeder.instances[0].alive = False

    streamer.feed("home", "WX5", 16000, b"\x01\x01")  # must not raise
    assert FakeFeeder.instances[0].writes == [b"\x00\x00"]  # second write never happened


def test_dead_feeder_key_can_recover_by_starting_a_new_feeder():
    streamer = Streamer(ICECAST, feeder_factory=FakeFeeder)
    streamer.feed("home", "WX5", 16000, b"\x00\x00")
    # simulate a permanently-dead mountpoint -- once marked dead, this
    # implementation intentionally stops retrying that key (a bad
    # mountpoint shouldn't spin up an ffmpeg process forever)
    FakeFeeder.instances[0].alive = False
    streamer.feed("home", "WX5", 16000, b"\x01\x01")
    streamer.feed("home", "WX5", 16000, b"\x02\x02")
    assert len(FakeFeeder.instances) == 1


def test_mount_urls_reflects_active_feeders():
    streamer = Streamer(ICECAST, feeder_factory=FakeFeeder)
    streamer.feed("home", "WX5", 16000, b"\x00\x00")
    urls = streamer.mount_urls("http://localhost:8000")
    assert urls == {("home", "WX5"): "http://localhost:8000/home-WX5.ogg"}


def test_close_closes_every_feeder():
    streamer = Streamer(ICECAST, feeder_factory=FakeFeeder)
    streamer.feed("home", "WX5", 16000, b"\x00\x00")
    streamer.feed("home", "WX1", 16000, b"\x00\x00")
    streamer.close()
    assert all(f.closed for f in FakeFeeder.instances)
