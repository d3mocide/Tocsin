from pathlib import Path

from api.config import ApiConfig


def test_from_env_defaults(monkeypatch):
    monkeypatch.delenv("API_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("API_REDIS_URL", raising=False)
    monkeypatch.delenv("API_PORT", raising=False)
    monkeypatch.delenv("API_STATIC_DIR", raising=False)

    config = ApiConfig.from_env()

    assert config.postgres_dsn is None
    assert config.redis_url == "redis://redis:6379/0"
    assert config.port == 8000
    assert config.consumer_name == "api"
    assert config.static_dir == Path("/app/static")


def test_from_env_reads_overrides(monkeypatch):
    monkeypatch.setenv("API_POSTGRES_DSN", "postgresql://tocsin:x@timescaledb:5432/tocsin")
    monkeypatch.setenv("API_PORT", "9000")
    monkeypatch.setenv("API_STATIC_DIR", "/tmp/web-dist")

    config = ApiConfig.from_env()

    assert config.postgres_dsn == "postgresql://tocsin:x@timescaledb:5432/tocsin"
    assert config.port == 9000
    assert config.static_dir == Path("/tmp/web-dist")


def test_from_env_empty_static_dir_disables_the_spa_mount(monkeypatch):
    monkeypatch.setenv("API_STATIC_DIR", "")

    config = ApiConfig.from_env()

    assert config.static_dir is None
