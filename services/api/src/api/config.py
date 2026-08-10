"""Env-derived configuration, kept as a plain frozen dataclass and a pure
`from_env()` -- no framework config object, matching every other service's
env-parsing style in this repo."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

DEFAULT_REDIS_URL = "redis://redis:6379/0"
DEFAULT_POSTGRES_HOST = "timescaledb"
DEFAULT_POSTGRES_PORT = "5432"
DEFAULT_POSTGRES_USER = "tocsin"
DEFAULT_POSTGRES_DB = "tocsin"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
DEFAULT_CONSUMER_NAME = "api"
# Where the Dockerfile's node build stage copies web/dist -- see
# services/api/Dockerfile. Doesn't exist in local `uv run pytest`/`uv run
# api` dev use; create_app only mounts it if static_dir.is_dir(), so a
# missing path there is silently "no SPA mounted," not an error.
DEFAULT_STATIC_DIR = "/app/static"
DEFAULT_MODE = "offgrid"
DEFAULT_ICECAST_HOST = "icecast"
DEFAULT_ICECAST_PORT = 8000
# `*` matches this repo's prior hardcoded behavior -- fine for
# localhost/LAN use (design doc §11, non-goals), not for a deployment
# reachable from the open internet. Set CORS_ALLOWED_ORIGINS to the
# reverse proxy's actual origin(s) once exposed; see .env.example.
DEFAULT_CORS_ALLOWED_ORIGINS = "*"


def _postgres_dsn_from_env() -> str | None:
    """`API_POSTGRES_DSN` wins when it's set (deployments that point api at
    an existing database keep giving it one string), but compose passes the
    parts instead and lets this assemble them.

    The parts are the safe form: a DSN interpolated in YAML as
    `postgresql://tocsin:${POSTGRES_PASSWORD}@...` silently becomes a
    *different* DSN the moment the password contains `@`, `:`, `/`, `?`, or
    `#` -- the URL parser splits on those first, so the connection fails
    with "password authentication failed" while the password in `.env` is
    in fact the right one. Percent-encoding each part removes that class of
    failure entirely."""
    dsn = os.environ.get("API_POSTGRES_DSN")
    if dsn:
        return dsn
    password = os.environ.get("API_POSTGRES_PASSWORD")
    if not password:
        return None
    user = quote(os.environ.get("API_POSTGRES_USER", DEFAULT_POSTGRES_USER), safe="")
    host = os.environ.get("API_POSTGRES_HOST", DEFAULT_POSTGRES_HOST)
    port = os.environ.get("API_POSTGRES_PORT", DEFAULT_POSTGRES_PORT)
    database = quote(os.environ.get("API_POSTGRES_DB", DEFAULT_POSTGRES_DB), safe="")
    return f"postgresql://{user}:{quote(password, safe='')}@{host}:{port}/{database}"


@dataclass(frozen=True)
class ApiConfig:
    postgres_dsn: str | None
    redis_url: str
    consumer_name: str
    host: str
    port: int
    static_dir: Path | None
    mode: str
    data_dir: Path | None
    captures_dir: Path | None
    icecast_host: str
    icecast_port: int
    # What the *browser* should use to reach Icecast, which is not what
    # this process uses: `icecast:8000` resolves inside the compose
    # network only. Left unset by default so the frontend falls back to
    # the page's own hostname on the Icecast port -- correct for the
    # normal "browse to the Pi on the LAN" case, and overridable for
    # deployments behind a reverse proxy where it isn't.
    icecast_public_url: str | None
    # Browser origins allowed to read this API cross-origin, e.g.
    # `https://tocsin.example.com`. Defaults to `*` -- every prior
    # deployment target here was localhost/LAN, where any origin reading
    # unauthenticated GET-only data is a non-issue. Narrow this once the
    # instance is reachable from the internet (comma-separated for more
    # than one origin); same-origin requests -- the normal case, since
    # `api` serves the built SPA itself -- never need this at all.
    cors_allowed_origins: tuple[str, ...]
    # Operator's approximate location, decimal degrees. Both unset (the
    # default) means reference.py's stations table carries no distance_km --
    # there's nothing wrong with that, it's the same "cosmetic lookup table,
    # degrade rather than fail" posture as the rest of this file. See
    # data/nwr_stations_or.yaml and services/api/README.md.
    latitude: float | None
    longitude: float | None

    @classmethod
    def from_env(cls) -> "ApiConfig":
        static_dir = os.environ.get("API_STATIC_DIR", DEFAULT_STATIC_DIR)
        data_dir = os.environ.get("TOCSIN_DATA_DIR")
        captures_dir = os.environ.get("API_CAPTURES_DIR")
        latitude = os.environ.get("TOCSIN_LATITUDE")
        longitude = os.environ.get("TOCSIN_LONGITUDE")
        cors_origins_raw = os.environ.get("CORS_ALLOWED_ORIGINS", DEFAULT_CORS_ALLOWED_ORIGINS)
        return cls(
            postgres_dsn=_postgres_dsn_from_env(),
            redis_url=os.environ.get("API_REDIS_URL", DEFAULT_REDIS_URL),
            consumer_name=os.environ.get("API_CONSUMER_NAME", DEFAULT_CONSUMER_NAME),
            host=os.environ.get("API_HOST", DEFAULT_HOST),
            port=int(os.environ.get("API_PORT", DEFAULT_PORT)),
            static_dir=Path(static_dir) if static_dir else None,
            mode=os.environ.get("TOCSIN_MODE", DEFAULT_MODE),
            data_dir=Path(data_dir) if data_dir else None,
            captures_dir=Path(captures_dir) if captures_dir else None,
            icecast_host=os.environ.get("ICECAST_HOST", DEFAULT_ICECAST_HOST),
            icecast_port=int(os.environ.get("ICECAST_PORT", DEFAULT_ICECAST_PORT)),
            icecast_public_url=os.environ.get("ICECAST_PUBLIC_URL") or None,
            cors_allowed_origins=tuple(origin.strip() for origin in cors_origins_raw.split(",") if origin.strip()),
            latitude=float(latitude) if latitude else None,
            longitude=float(longitude) if longitude else None,
        )
