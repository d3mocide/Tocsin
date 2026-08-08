"""Icecast stream metadata (name/description/genre, shown on Icecast's
status page and in players) -- deployment-specific labeling, not shared
reference data, so it's configured here via env vars/an optional YAML
file rather than living in `data/` alongside the SAME/CAP mappings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_NAME_TEMPLATE = "Tocsin {site} {channel}"
DEFAULT_DESCRIPTION = "Tocsin NOAA Weather Radio relay"
DEFAULT_GENRE = "weather"


@dataclass(frozen=True)
class StreamMetadata:
    name: str
    description: str
    genre: str


@dataclass(frozen=True)
class MetadataConfig:
    """`site_names`/`channel_names` are optional display-name overrides --
    e.g. showing the `home` site from `SDR_RX_DEVICES` as "Portland Home
    Station" -- looked up by the raw site/channel strings used everywhere
    else (mount names, ZMQ topics). Everything else is one global
    template: one Icecast instance is one deployment, not one string per
    mount."""

    name_template: str = DEFAULT_NAME_TEMPLATE
    description: str = DEFAULT_DESCRIPTION
    genre: str = DEFAULT_GENRE
    site_names: dict[str, str] = field(default_factory=dict)
    channel_names: dict[str, str] = field(default_factory=dict)

    def resolve(self, site: str, channel: str) -> StreamMetadata:
        name = self.name_template.format(
            site=self.site_names.get(site, site),
            channel=self.channel_names.get(channel, channel),
        )
        return StreamMetadata(name=name, description=self.description, genre=self.genre)


def load_site_and_channel_names(path: str | Path | None) -> tuple[dict[str, str], dict[str, str]]:
    """Load the optional `site_names`/`channel_names` overrides from a YAML
    file. Returns empty mappings when `path` is unset -- the env-var
    template alone (raw site/channel codes) is a complete, if less
    friendly, default, so this file is opt-in rather than required.
    """
    if not path:
        return {}, {}
    with Path(path).open() as f:
        raw = yaml.safe_load(f) or {}
    return raw.get("site_names") or {}, raw.get("channel_names") or {}
