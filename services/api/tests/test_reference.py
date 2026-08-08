from pathlib import Path

from api import reference

REPO_DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def test_missing_data_dir_degrades_to_empty_rather_than_raising():
    """Every other service exits 1 on a missing data/ file -- correctly,
    since a decoder with no tier table would mis-tier a warning. Here the
    only stake is county names vs raw codes in the UI, and refusing to
    serve the alert feed over that would be the worse failure."""
    assert reference.load(None) is reference.EMPTY
    assert reference.load(Path("/nonexistent")).event_codes == {}


def test_loads_the_repo_reference_data(tmp_path):
    loaded = reference.load(REPO_DATA_DIR)

    assert loaded.event_codes["TOR"] == {"name": "Tornado Warning", "tier": "A"}
    # Tier is the field the UI cannot render an alert honestly without:
    # a TOR and an RWT look identical on screen without it, though one
    # goes to the mesh immediately and the other is logged and ignored.
    assert loaded.event_codes["RWT"]["tier"] == "C"
    assert loaded.counties["41051"] == {"county": "Multnomah", "state": "OR"}


def test_a_partial_data_dir_loads_what_is_there(tmp_path):
    (tmp_path / "fips.csv").write_text("fips,county,state\n41051,Multnomah,OR\n")

    loaded = reference.load(tmp_path)

    assert loaded.counties == {"41051": {"county": "Multnomah", "state": "OR"}}
    assert loaded.event_codes == {}


def test_as_dict_shape_is_what_the_frontend_consumes(tmp_path):
    (tmp_path / "fips.csv").write_text("fips,county,state\n41051,Multnomah,OR\n")

    assert reference.load(tmp_path).as_dict() == {
        "event_codes": {},
        "counties": {"41051": {"county": "Multnomah", "state": "OR"}},
    }


def test_a_malformed_event_code_entry_is_skipped(tmp_path):
    (tmp_path / "same_event_codes.yaml").write_text("TOR: {name: Tornado Warning, tier: A}\nBAD: just-a-string\n")

    loaded = reference.load(tmp_path)

    assert "TOR" in loaded.event_codes
    assert "BAD" not in loaded.event_codes
