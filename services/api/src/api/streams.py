"""Lists the Icecast mountpoints `live_audio` is pushing, so the UI can
offer a play button instead of leaving the streams discoverable only by
someone who has read `live_audio/feeder.py` and knows to paste
`http://host:8000/home-WX1.ogg` into VLC.

Two independent sources, merged, because each knows something the other
doesn't:

- **Icecast's `/status-json.xsl`** knows what is actually being served
  right now and how many listeners each mount has, but it only lists
  *connected* sources -- a channel whose ffmpeg died vanishes from it
  entirely, which is the one moment you most want to see the channel.
- **`live_audio`'s heartbeat** (`tocsin:status:live_audio`, `detail.mounts`)
  knows every (site, channel) that process has ever fed, including the
  ones it has marked dead, and survives Icecast itself being unreachable.

This is a LAN service, not an internet one, so nothing here violates the
offgrid contract (design doc §8) -- Icecast runs in the same compose
project. A failure to reach it degrades to the heartbeat-only view rather
than erroring, since "Icecast is down" is itself a thing the page should
be able to show.

Playback URLs are handed to the browser as direct Icecast URLs rather than
proxied through this process: an `<audio>` element streams cross-origin
without CORS, and proxying continuous audio would pin a uvicorn connection
open per listener for no benefit.
"""

from __future__ import annotations

import json

DEFAULT_TIMEOUT_SECONDS = 2.0
STATUS_PATH = "/status-json.xsl"


def public_base_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def _as_list(value) -> list:
    """Icecast's status JSON gives `source` as a bare object when exactly
    one mount is connected and a list when there are several -- a
    long-standing quirk of its JSON serializer, not a version difference,
    so both shapes have to be handled every time."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def parse_icecast_status(payload: dict) -> dict[str, dict]:
    """Maps mount ("/home-WX1.ogg") -> the fields worth showing."""
    sources = _as_list((payload.get("icestats") or {}).get("source"))
    parsed = {}
    for source in sources:
        mount = source.get("listenurl", "")
        mount = mount[mount.rfind("/") :] if "/" in mount else mount
        if not mount:
            continue
        parsed[mount] = {
            "listeners": source.get("listeners"),
            "stream_name": source.get("server_name"),
            "description": source.get("server_description"),
            "bitrate": source.get("bitrate"),
            "started_at": source.get("stream_start_iso8601") or source.get("stream_start"),
        }
    return parsed


async def fetch_icecast_status(http_get, base_url: str) -> dict[str, dict] | None:
    """`None` means Icecast could not be reached -- distinct from `{}`,
    which means it answered and has no sources connected. The UI shows
    those differently ("Icecast unreachable" vs "no streams running")."""
    try:
        body = await http_get(f"{base_url}{STATUS_PATH}")
    except Exception:
        return None
    if body is None:
        return None
    try:
        return parse_icecast_status(json.loads(body))
    except ValueError:
        return None


def mounts_from_heartbeat(heartbeat: dict | None) -> list[dict]:
    if not heartbeat:
        return []
    return list((heartbeat.get("detail") or {}).get("mounts") or [])


def merge(known_mounts: list[dict], icecast: dict[str, dict] | None, base_url: str) -> list[dict]:
    """`known_mounts` is live_audio's own view; `icecast` is what the
    server admits to serving. A mount in either shows up in the result --
    feeder-alive-but-Icecast-doesn't-have-it is a real and diagnosable
    state (bad source password, usually), and dropping it would hide the
    single most common Icecast misconfiguration."""
    by_mount: dict[str, dict] = {}
    for entry in known_mounts:
        mount = entry.get("mount")
        if not mount:
            continue
        by_mount[mount] = {
            "mount": mount,
            "site": entry.get("site"),
            "channel": entry.get("channel"),
            "feeder_alive": bool(entry.get("alive")),
            "url": f"{base_url}{mount}",
            "on_air": False,
            "listeners": None,
            "stream_name": None,
        }

    for mount, info in (icecast or {}).items():
        row = by_mount.setdefault(
            mount,
            {
                "mount": mount,
                "site": None,
                "channel": None,
                # Unknown, not False: live_audio's heartbeat is missing
                # (or this mount predates it), so claiming its feeder is
                # dead while Icecast is actively serving it would be a lie.
                "feeder_alive": None,
                "url": f"{base_url}{mount}",
                "on_air": False,
                "listeners": None,
                "stream_name": None,
            },
        )
        row["on_air"] = True
        row["listeners"] = info.get("listeners")
        row["stream_name"] = info.get("stream_name")

    return sorted(by_mount.values(), key=lambda row: row["mount"])
