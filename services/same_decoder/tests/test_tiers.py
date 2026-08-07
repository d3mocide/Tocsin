import pytest
import yaml

from same_decoder.tiers import TierTable


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
