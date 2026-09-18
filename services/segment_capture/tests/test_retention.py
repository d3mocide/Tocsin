import time

from segment_capture.retention import is_live_capture, prune_captures


def _touch(path, age_seconds, now):
    path.write_bytes(b"\x00")
    mtime = now - age_seconds
    import os

    os.utime(path, (mtime, mtime))


def test_is_live_capture_matches_live_segmenter_filenames():
    from pathlib import Path

    assert is_live_capture(Path("PDX-WX7-live-1700000000000.wav"))
    assert not is_live_capture(Path("PDX-WX7-TOR-1700000000.wav"))


def test_prune_deletes_only_expired_files_using_kind_specific_retention(tmp_path):
    now = time.time()
    live_fresh = tmp_path / "PDX-WX7-live-1.wav"
    live_stale = tmp_path / "PDX-WX7-live-2.wav"
    alert_fresh = tmp_path / "PDX-WX7-TOR-3.wav"
    alert_stale = tmp_path / "PDX-WX7-TOR-4.wav"

    _touch(live_fresh, age_seconds=10, now=now)
    _touch(live_stale, age_seconds=1000, now=now)
    _touch(alert_fresh, age_seconds=1000, now=now)
    _touch(alert_stale, age_seconds=100_000, now=now)

    deleted = prune_captures(
        tmp_path,
        live_retention_seconds=500,
        alert_retention_seconds=10_000,
        now_fn=lambda: now,
    )

    assert set(deleted) == {live_stale, alert_stale}
    assert live_fresh.exists()
    assert alert_fresh.exists()
    assert not live_stale.exists()
    assert not alert_stale.exists()


def test_prune_ignores_non_wav_files(tmp_path):
    now = time.time()
    sidecar = tmp_path / "PDX-WX7-live-1.meta.json"
    _touch(sidecar, age_seconds=1_000_000, now=now)

    deleted = prune_captures(tmp_path, live_retention_seconds=1, alert_retention_seconds=1, now_fn=lambda: now)

    assert deleted == []
    assert sidecar.exists()


def test_prune_missing_directory_returns_empty(tmp_path):
    assert prune_captures(tmp_path / "does-not-exist") == []
