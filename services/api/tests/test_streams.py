import json

from api import streams

BASE = "http://icecast:8000"


def _icestats(sources):
    return json.dumps({"icestats": {"source": sources}})


def test_a_single_source_arrives_as_an_object_not_a_list():
    """Icecast's JSON serializer emits `source` as a bare object when
    exactly one mount is connected and a list otherwise -- a long-standing
    quirk, not a version difference, so both shapes have to work."""
    one = {"listenurl": "http://icecast:8000/home-WX1.ogg", "listeners": 2}

    assert streams.parse_icecast_status({"icestats": {"source": one}}) == {
        "/home-WX1.ogg": {
            "listeners": 2,
            "stream_name": None,
            "description": None,
            "bitrate": None,
            "started_at": None,
        }
    }


def test_multiple_sources_arrive_as_a_list():
    parsed = streams.parse_icecast_status(
        {
            "icestats": {
                "source": [
                    {"listenurl": "http://icecast:8000/home-WX1.ogg", "listeners": 1},
                    {"listenurl": "http://icecast:8000/home-WX5.ogg", "listeners": 0},
                ]
            }
        }
    )

    assert set(parsed) == {"/home-WX1.ogg", "/home-WX5.ogg"}


def test_no_sources_connected_parses_to_empty():
    assert streams.parse_icecast_status({"icestats": {}}) == {}


async def test_unreachable_icecast_is_none_not_empty():
    """`None` (couldn't ask) and `{}` (asked, nothing running) are
    different things the UI shows differently."""

    async def failing_get(url):
        raise OSError("connection refused")

    assert await streams.fetch_icecast_status(failing_get, BASE) is None


async def test_non_json_response_is_treated_as_unreachable():
    async def html_get(url):
        return "<html>404</html>"

    assert await streams.fetch_icecast_status(html_get, BASE) is None


async def test_reachable_icecast_with_no_sources_is_empty_dict():
    async def empty_get(url):
        return _icestats([])

    assert await streams.fetch_icecast_status(empty_get, BASE) == {}


def test_merge_marks_a_feeder_alive_mount_that_icecast_does_not_serve():
    """Feeder running but Icecast not serving it is the single most common
    Icecast misconfiguration (wrong source password). Dropping the row
    would hide exactly that."""
    known = [{"site": "home", "channel": "WX1", "mount": "/home-WX1.ogg", "alive": True}]

    merged = streams.merge(known, {}, BASE)

    assert merged == [
        {
            "mount": "/home-WX1.ogg",
            "site": "home",
            "channel": "WX1",
            "feeder_alive": True,
            "url": "http://icecast:8000/home-WX1.ogg",
            "on_air": False,
            "listeners": None,
            "stream_name": None,
        }
    ]


def test_merge_keeps_a_dead_feeder_that_icecast_has_already_dropped():
    known = [{"site": "home", "channel": "WX1", "mount": "/home-WX1.ogg", "alive": False}]

    merged = streams.merge(known, {}, BASE)

    assert merged[0]["feeder_alive"] is False
    assert merged[0]["on_air"] is False


def test_merge_combines_both_sources_for_a_healthy_mount():
    known = [{"site": "home", "channel": "WX1", "mount": "/home-WX1.ogg", "alive": True}]
    icecast = {"/home-WX1.ogg": {"listeners": 3, "stream_name": "Tocsin home WX1"}}

    merged = streams.merge(known, icecast, BASE)

    assert merged[0]["on_air"] is True
    assert merged[0]["listeners"] == 3
    assert merged[0]["stream_name"] == "Tocsin home WX1"


def test_a_mount_only_icecast_knows_about_has_unknown_feeder_state():
    """Not False: claiming the feeder is dead while Icecast is actively
    serving the mount would be a lie."""
    merged = streams.merge([], {"/home-WX1.ogg": {"listeners": 0}}, BASE)

    assert merged[0]["feeder_alive"] is None
    assert merged[0]["on_air"] is True


def test_playback_url_uses_the_public_base_not_the_internal_one():
    """`icecast:8000` only resolves inside the compose network; the
    browser needs the LAN address."""
    known = [{"site": "home", "channel": "WX1", "mount": "/home-WX1.ogg", "alive": True}]

    merged = streams.merge(known, None, "http://pi.local:8000")

    assert merged[0]["url"] == "http://pi.local:8000/home-WX1.ogg"


def test_mounts_from_a_missing_heartbeat_is_empty():
    assert streams.mounts_from_heartbeat(None) == []
    assert streams.mounts_from_heartbeat({}) == []
    assert streams.mounts_from_heartbeat({"detail": {}}) == []
