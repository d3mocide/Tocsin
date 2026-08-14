import pytest
import yaml

from stt_worker.keyword_match import KeywordMatcher, _default_data_dir


def _write_tables(tmp_path, triggers: dict, codes: dict) -> None:
    (tmp_path / "keyword_triggers.yaml").write_text(yaml.dump(triggers))
    (tmp_path / "same_event_codes.yaml").write_text(yaml.dump(codes))


def test_loads_real_checked_in_tables():
    matcher = KeywordMatcher.load()  # default path resolves to the repo's data/
    match = matcher.match("the national weather service has issued a tornado warning for your area")
    assert match is not None
    assert match.event_code == "TOR"
    assert match.tier == "A"
    assert match.matched_phrase == "tornado warning"


def test_no_match_returns_none(tmp_path):
    _write_tables(
        tmp_path,
        {"TOR": {"phrases": ["tornado warning"]}},
        {"TOR": {"name": "Tornado Warning", "tier": "A"}},
    )
    matcher = KeywordMatcher.load(tmp_path)
    assert matcher.match("mostly cloudy tonight with a light breeze") is None


def test_match_is_case_insensitive(tmp_path):
    _write_tables(
        tmp_path,
        {"TOR": {"phrases": ["tornado warning"]}},
        {"TOR": {"name": "Tornado Warning", "tier": "A"}},
    )
    matcher = KeywordMatcher.load(tmp_path)
    match = matcher.match("A TORNADO WARNING has been issued")
    assert match is not None
    assert match.event_code == "TOR"


def test_match_requires_whole_word_boundaries(tmp_path):
    _write_tables(
        tmp_path,
        {"FLW": {"phrases": ["flood warning"]}},
        {"FLW": {"name": "Flood Warning", "tier": "B"}},
    )
    matcher = KeywordMatcher.load(tmp_path)
    # "floodwarning" run together as one word must not match "flood warning".
    assert matcher.match("floodwarning system test") is None
    assert matcher.match("a flood warning is in effect") is not None


def test_longest_phrase_wins_on_overlap(tmp_path):
    _write_tables(
        tmp_path,
        {
            "FFA": {"phrases": ["flash flood"]},
            "FFW": {"phrases": ["flash flood warning"]},
        },
        {
            "FFA": {"name": "Flash Flood Watch", "tier": "B"},
            "FFW": {"name": "Flash Flood Warning", "tier": "A"},
        },
    )
    matcher = KeywordMatcher.load(tmp_path)
    match = matcher.match("a flash flood warning is in effect until 5pm")
    assert match.event_code == "FFW"


def test_unknown_event_code_falls_back_to_tier_b_with_placeholder_name(tmp_path):
    _write_tables(tmp_path, {"ZZZ": {"phrases": ["made up phrase"]}}, {})
    matcher = KeywordMatcher.load(tmp_path)
    match = matcher.match("this contains a made up phrase indeed")
    assert match.tier == "B"
    assert "ZZZ" in match.event_name


def test_missing_file_raises(tmp_path):
    with pytest.raises(OSError):
        KeywordMatcher.load(tmp_path)


def test_default_data_dir_raises_clearly_when_tree_is_too_shallow():
    with pytest.raises(RuntimeError, match="TOCSIN_DATA_DIR"):
        _default_data_dir(module_file="/app/src/stt_worker/keyword_match.py")


def test_default_data_dir_resolves_repo_root_in_a_full_checkout():
    import stt_worker.keyword_match as keyword_match_module

    resolved = _default_data_dir(module_file=keyword_match_module.__file__)
    assert (resolved / "keyword_triggers.yaml").exists()
