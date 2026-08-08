import pytest
import yaml

from same_decoder.tiers import TierTable, _default_data_dir


def test_loads_real_checked_in_event_code_table():
    tiers = TierTable.load()  # default path resolves to the repo's data/
    assert tiers.lookup("TOR") == ("Tornado Warning", "A")
    assert tiers.lookup("RWT") == ("Required Weekly Test", "C")
    assert tiers.lookup("SVA") == ("Severe Thunderstorm Watch", "B")


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
    """Regression test: inside the Docker image the copied tree is
    flattened to /app/src/same_decoder/tiers.py, with nothing 4 parents up
    -- this used to be an eager module-level IndexError on every import
    (crash-looped the container even with TOCSIN_DATA_DIR correctly set,
    since load() never got a chance to use it). Verified against a real
    build: docker compose logs showed the container crash-looping on
    `Path(__file__).resolve().parents[4]` before this fix."""
    with pytest.raises(RuntimeError, match="TOCSIN_DATA_DIR"):
        _default_data_dir(module_file="/app/src/same_decoder/tiers.py")


def test_default_data_dir_resolves_repo_root_in_a_full_checkout():
    import same_decoder.tiers as tiers_module

    resolved = _default_data_dir(module_file=tiers_module.__file__)
    assert (resolved / "same_event_codes.yaml").exists()
