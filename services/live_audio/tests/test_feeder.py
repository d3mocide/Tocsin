import sys
import time

from live_audio.feeder import FFmpegFeeder, build_ffmpeg_command, icecast_source_url, mount_name


def test_mount_name_combines_site_and_channel():
    assert mount_name("home", "WX5") == "/home-WX5.ogg"


def test_icecast_source_url_shape():
    url = icecast_source_url("icecast", 8000, "source", "hackme", "/home-WX5.ogg")
    assert url == "icecast://source:hackme@icecast:8000/home-WX5.ogg"


def test_build_ffmpeg_command_uses_given_sample_rate_and_url():
    cmd = build_ffmpeg_command("icecast://source:hackme@icecast:8000/home-WX5.ogg", 16000)
    assert cmd[0] == "ffmpeg"
    assert "-ar" in cmd and cmd[cmd.index("-ar") + 1] == "16000"
    assert cmd[-1] == "icecast://source:hackme@icecast:8000/home-WX5.ogg"
    assert "-f" in cmd and "ogg" in cmd


def test_build_ffmpeg_command_omits_metadata_flags_by_default():
    cmd = build_ffmpeg_command("icecast://source:hackme@icecast:8000/home-WX5.ogg", 16000)
    assert "-ice_name" not in cmd
    assert "-ice_description" not in cmd
    assert "-ice_genre" not in cmd


def test_build_ffmpeg_command_includes_given_metadata_flags():
    cmd = build_ffmpeg_command(
        "icecast://source:hackme@icecast:8000/home-WX5.ogg",
        16000,
        stream_name="Tocsin home WX5",
        stream_description="Tocsin NOAA Weather Radio relay",
        stream_genre="weather",
    )
    assert cmd[cmd.index("-ice_name") + 1] == "Tocsin home WX5"
    assert cmd[cmd.index("-ice_description") + 1] == "Tocsin NOAA Weather Radio relay"
    assert cmd[cmd.index("-ice_genre") + 1] == "weather"
    # metadata flags are protocol options -- must still land before the output URL
    assert cmd.index("-ice_name") < cmd.index("icecast://source:hackme@icecast:8000/home-WX5.ogg")


def _fake_ffmpeg_command() -> list[str]:
    """Stand-in for ffmpeg: reads stdin to EOF (as the real process would
    keep consuming PCM until the pipe closes) and exits 0."""
    return [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"]


def _fake_ffmpeg_command_that_exits_immediately() -> list[str]:
    return [sys.executable, "-c", "pass"]


def test_write_does_not_raise_against_a_live_process():
    feeder = FFmpegFeeder(_fake_ffmpeg_command())
    feeder.write(b"\x00\x00\x00\x00")
    assert feeder.is_alive()
    feeder.close()


def test_close_terminates_the_process():
    feeder = FFmpegFeeder(_fake_ffmpeg_command())
    feeder.close()
    assert not feeder.is_alive()


def test_is_alive_false_once_the_process_exits_on_its_own():
    feeder = FFmpegFeeder(_fake_ffmpeg_command_that_exits_immediately())
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and feeder.is_alive():
        time.sleep(0.02)
    assert not feeder.is_alive()
    feeder.close()
