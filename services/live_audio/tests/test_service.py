from live_audio.metadata import MetadataConfig
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


def test_dead_feeder_does_not_respawn_before_the_retry_interval():
    streamer = Streamer(ICECAST, feeder_factory=FakeFeeder)
    streamer.feed("home", "WX5", 16000, b"\x00\x00")
    # a bad mountpoint shouldn't spin up a new ffmpeg process on every
    # ~55ms audio chunk -- respawning is throttled to the retry interval
    FakeFeeder.instances[0].alive = False
    streamer.feed("home", "WX5", 16000, b"\x01\x01")
    streamer.feed("home", "WX5", 16000, b"\x02\x02")
    assert len(FakeFeeder.instances) == 1


def test_dead_feeder_key_recovers_by_starting_a_new_feeder_after_the_retry_interval():
    """A feeder can die for reasons that clear up on their own (an Icecast
    restart, a dropped TCP connection, ffmpeg getting OOM-killed) and
    live_audio runs for days between restarts -- so a dead mount must not
    stay "FEEDER DEAD" forever once the backoff window has passed."""
    clock = [0.0]
    streamer = Streamer(ICECAST, feeder_factory=FakeFeeder, retry_interval_seconds=30.0, now_fn=lambda: clock[0])
    streamer.feed("home", "WX5", 16000, b"\x00\x00")
    FakeFeeder.instances[0].alive = False

    streamer.feed("home", "WX5", 16000, b"\x01\x01")  # notices the death, starts backing off
    clock[0] += 10.0
    streamer.feed("home", "WX5", 16000, b"\x02\x02")  # still within the backoff window
    assert len(FakeFeeder.instances) == 1

    clock[0] += 30.0
    streamer.feed("home", "WX5", 16000, b"\x03\x03")  # backoff window has elapsed -- retries
    assert len(FakeFeeder.instances) == 2
    assert FakeFeeder.instances[1].writes == [b"\x03\x03"]
    assert streamer.mounts() == [
        {"site": "home", "channel": "WX5", "mount": "/home-WX5.ogg", "alive": True}
    ]


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


def test_feed_builds_default_metadata_into_the_ffmpeg_command():
    streamer = Streamer(ICECAST, feeder_factory=FakeFeeder)
    streamer.feed("home", "WX5", 16000, b"\x00\x00")
    command = FakeFeeder.instances[0].command
    assert command[command.index("-ice_name") + 1] == "Tocsin home WX5"


def test_feed_uses_given_metadata_config():
    metadata = MetadataConfig(site_names={"home": "Portland Home Station"})
    streamer = Streamer(ICECAST, metadata, feeder_factory=FakeFeeder)
    streamer.feed("home", "WX5", 16000, b"\x00\x00")
    command = FakeFeeder.instances[0].command
    assert command[command.index("-ice_name") + 1] == "Tocsin Portland Home Station WX5"


def test_mounts_reports_a_live_feeder():
    streamer = Streamer(ICECAST, feeder_factory=FakeFeeder)
    streamer.feed("home", "WX1", 22050, b"\x00\x00")

    assert streamer.mounts() == [
        {"site": "home", "channel": "WX1", "mount": "/home-WX1.ogg", "alive": True}
    ]


def test_mounts_still_reports_a_feeder_that_died():
    """Icecast stops listing a mount whose source disconnected, which is
    the one moment you most want to see the channel -- so live_audio
    reports its own view, including the feeders it has given up on."""
    streamer = Streamer(ICECAST, feeder_factory=FakeFeeder)
    streamer.feed("home", "WX1", 22050, b"\x00\x00")
    FakeFeeder.instances[0].alive = False
    streamer.feed("home", "WX1", 22050, b"\x00\x00")  # notices the death

    assert streamer.mounts() == [
        {"site": "home", "channel": "WX1", "mount": "/home-WX1.ogg", "alive": False}
    ]


def test_mounts_of_a_streamer_that_has_fed_nothing_is_empty():
    assert Streamer(ICECAST, feeder_factory=FakeFeeder).mounts() == []


def test_channel_outside_allowlist_never_gets_a_feeder():
    streamer = Streamer(ICECAST, feeder_factory=FakeFeeder, allowed_channels=frozenset({"WX5"}))
    streamer.feed("home", "WX1", 16000, b"\x00\x00")
    assert FakeFeeder.instances == []
    assert streamer.mounts() == []


def test_channel_inside_allowlist_streams_normally():
    streamer = Streamer(ICECAST, feeder_factory=FakeFeeder, allowed_channels=frozenset({"WX5"}))
    streamer.feed("home", "WX5", 16000, b"\x00\x00")
    assert len(FakeFeeder.instances) == 1
    assert FakeFeeder.instances[0].writes == [b"\x00\x00"]


def test_no_allowlist_streams_every_channel():
    streamer = Streamer(ICECAST, feeder_factory=FakeFeeder, allowed_channels=None)
    streamer.feed("home", "WX1", 16000, b"\x00\x00")
    streamer.feed("home", "WX7", 16000, b"\x00\x00")
    assert len(FakeFeeder.instances) == 2
