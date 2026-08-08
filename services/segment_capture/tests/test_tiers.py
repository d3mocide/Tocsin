import pytest
import yaml

from segment_capture.tiers import TierTable, _default_data_dir


def test_loads_real_checked_in_event_code_table():
    tiers = TierTable.load()  # default path resolves to the repo's data/
    assert tiers.lookup("TOR") == ("Tornado Warning", "A")
    assert tiers.lookup("RWT") == ("Required Weekly Test", "C")


def test_unknown_code_falls_back_to_tier_b_with_a_visible_placeholder():
    tiers = TierTable(codes={"TOR": {"name": "Tornado Warning", "tier": "A"}})
    name, tier = tiers.lookup("ZZZ")
    assert tier == "B"
    assert "ZZZ" in name


def test_load_from_explicit_directory(tmp_path):
    (tmp_path / "same_event_codes.yaml").write_text(
        yaml.dump({"TOR": {"name": "Tornado Warning", "tier": "A"}})
    )
    tiers = TierTable.load(tmp_path)
    assert tiers.lookup("TOR") == ("Tornado Warning", "A")


def test_missing_file_raises(tmp_path):
    with pytest.raises(OSError):
        TierTable.load(tmp_path)


def test_default_data_dir_raises_clearly_when_tree_is_too_shallow():
    """Same class of bug same_decoder/tiers.py's own regression test
    guards against (docs/design/tracking.md, 2026-08-08): a module-level
    `.parents[4]` would crash-loop the container on import inside Docker's
    flattened `/app/src/...` tree. Written as a lazy function from the
    start here, but tested anyway since the failure mode is severe enough
    to be worth locking in explicitly, not just inferring from the other
    service's fix."""
    with pytest.raises(RuntimeError, match="TOCSIN_DATA_DIR"):
        _default_data_dir(module_file="/app/src/segment_capture/tiers.py")


def test_default_data_dir_resolves_repo_root_in_a_full_checkout():
    import segment_capture.tiers as tiers_module

    resolved = _default_data_dir(module_file=tiers_module.__file__)
    assert (resolved / "same_event_codes.yaml").exists()
