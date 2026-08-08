from segment_capture import _build_redis_client


def test_no_redis_url_means_no_client(monkeypatch):
    monkeypatch.delenv("SEGMENT_CAPTURE_REDIS_URL", raising=False)

    assert _build_redis_client() is None


def test_a_configured_url_builds_a_client(monkeypatch):
    """Guards the dependency, not the URL parsing: `redis` is imported
    lazily here, so leaving it out of pyproject.toml passes every other
    test in this suite and then crash-loops the container on its first
    heartbeat. `from_url` connects lazily, so this needs no live Redis."""
    monkeypatch.setenv("SEGMENT_CAPTURE_REDIS_URL", "redis://redis:6379/0")

    assert _build_redis_client() is not None
