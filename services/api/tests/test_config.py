from pathlib import Path

from api.config import ApiConfig


def test_from_env_defaults(monkeypatch):
    monkeypatch.delenv("API_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("API_POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("API_REDIS_URL", raising=False)
    monkeypatch.delenv("API_PORT", raising=False)
    monkeypatch.delenv("API_STATIC_DIR", raising=False)
    monkeypatch.delenv("ICECAST_HOST", raising=False)
    monkeypatch.delenv("ICECAST_PORT", raising=False)

    config = ApiConfig.from_env()

    assert config.postgres_dsn is None
    assert config.redis_url == "redis://redis:6379/0"
    assert config.port == 8000
    assert config.consumer_name == "api"
    assert config.static_dir == Path("/app/static")
    assert config.icecast_host == "icecast"
    assert config.icecast_port == 8000


def test_from_env_reads_overrides(monkeypatch):
    monkeypatch.setenv("API_POSTGRES_DSN", "postgresql://tocsin:x@timescaledb:5432/tocsin")
    monkeypatch.setenv("API_PORT", "9000")
    monkeypatch.setenv("API_STATIC_DIR", "/tmp/web-dist")

    config = ApiConfig.from_env()

    assert config.postgres_dsn == "postgresql://tocsin:x@timescaledb:5432/tocsin"
    assert config.port == 9000
    assert config.static_dir == Path("/tmp/web-dist")


def test_postgres_dsn_is_assembled_from_the_parts_compose_passes(monkeypatch):
    monkeypatch.delenv("API_POSTGRES_DSN", raising=False)
    monkeypatch.setenv("API_POSTGRES_PASSWORD", "changeme")

    config = ApiConfig.from_env()

    assert config.postgres_dsn == "postgresql://tocsin:changeme@timescaledb:5432/tocsin"


def test_postgres_dsn_percent_encodes_a_password_with_url_characters(monkeypatch):
    """The failure this exists to prevent: `p@ss:w/rd` interpolated straight
    into a DSN parses as host `ss`, and the resulting "password
    authentication failed" points at .env, where the password is correct."""
    monkeypatch.delenv("API_POSTGRES_DSN", raising=False)
    monkeypatch.setenv("API_POSTGRES_PASSWORD", "p@ss:w/rd#1?x")

    from urllib.parse import urlsplit

    parsed = urlsplit(ApiConfig.from_env().postgres_dsn)

    assert parsed.password == "p%40ss%3Aw%2Frd%231%3Fx"
    assert parsed.hostname == "timescaledb"
    assert parsed.port == 5432
    assert parsed.path == "/tocsin"


def test_an_explicit_dsn_still_wins_over_the_parts(monkeypatch):
    monkeypatch.setenv("API_POSTGRES_DSN", "postgresql://other@db.lan:6432/other")
    monkeypatch.setenv("API_POSTGRES_PASSWORD", "changeme")

    assert ApiConfig.from_env().postgres_dsn == "postgresql://other@db.lan:6432/other"


def test_from_env_reads_a_relocated_icecast(monkeypatch):
    """`ICECAST_PORT` is the port the browser is told to use as well as the
    one this process dials (see `GET /system`), so it has to survive the
    round trip as an int, not a string -- `icecast_port` lands in JSON."""
    monkeypatch.setenv("ICECAST_HOST", "icecast.lan")
    monkeypatch.setenv("ICECAST_PORT", "8100")

    config = ApiConfig.from_env()

    assert config.icecast_host == "icecast.lan"
    assert config.icecast_port == 8100


def test_from_env_empty_static_dir_disables_the_spa_mount(monkeypatch):
    monkeypatch.setenv("API_STATIC_DIR", "")

    config = ApiConfig.from_env()

    assert config.static_dir is None
