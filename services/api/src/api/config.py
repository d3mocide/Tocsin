"""Env-derived configuration, kept as a plain frozen dataclass and a pure
`from_env()` -- no framework config object, matching every other service's
env-parsing style in this repo."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_REDIS_URL = "redis://redis:6379/0"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
DEFAULT_CONSUMER_NAME = "api"


@dataclass(frozen=True)
class ApiConfig:
    postgres_dsn: str | None
    redis_url: str
    consumer_name: str
    host: str
    port: int

    @classmethod
    def from_env(cls) -> "ApiConfig":
        return cls(
            postgres_dsn=os.environ.get("API_POSTGRES_DSN"),
            redis_url=os.environ.get("API_REDIS_URL", DEFAULT_REDIS_URL),
            consumer_name=os.environ.get("API_CONSUMER_NAME", DEFAULT_CONSUMER_NAME),
            host=os.environ.get("API_HOST", DEFAULT_HOST),
            port=int(os.environ.get("API_PORT", DEFAULT_PORT)),
        )
