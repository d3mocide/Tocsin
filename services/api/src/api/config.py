"""Env-derived configuration, kept as a plain frozen dataclass and a pure
`from_env()` -- no framework config object, matching every other service's
env-parsing style in this repo."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_REDIS_URL = "redis://redis:6379/0"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
DEFAULT_CONSUMER_NAME = "api"
# Where the Dockerfile's node build stage copies web/dist -- see
# services/api/Dockerfile. Doesn't exist in local `uv run pytest`/`uv run
# api` dev use; create_app only mounts it if static_dir.is_dir(), so a
# missing path there is silently "no SPA mounted," not an error.
DEFAULT_STATIC_DIR = "/app/static"


@dataclass(frozen=True)
class ApiConfig:
    postgres_dsn: str | None
    redis_url: str
    consumer_name: str
    host: str
    port: int
    static_dir: Path | None

    @classmethod
    def from_env(cls) -> "ApiConfig":
        static_dir = os.environ.get("API_STATIC_DIR", DEFAULT_STATIC_DIR)
        return cls(
            postgres_dsn=os.environ.get("API_POSTGRES_DSN"),
            redis_url=os.environ.get("API_REDIS_URL", DEFAULT_REDIS_URL),
            consumer_name=os.environ.get("API_CONSUMER_NAME", DEFAULT_CONSUMER_NAME),
            host=os.environ.get("API_HOST", DEFAULT_HOST),
            port=int(os.environ.get("API_PORT", DEFAULT_PORT)),
            static_dir=Path(static_dir) if static_dir else None,
        )
