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
    assert loaded.stations["KIG98"]["name"] == "Portland"
    assert loaded.stations["KIG98"]["frequency_mhz"] == 162.550
    # No operator location configured in this call -- every station's
    # distance is unknown, not zero.
    assert loaded.stations["KIG98"]["distance_km"] is None


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
        "stations": {},
    }


def test_a_malformed_event_code_entry_is_skipped(tmp_path):
    (tmp_path / "same_event_codes.yaml").write_text("TOR: {name: Tornado Warning, tier: A}\nBAD: just-a-string\n")

    loaded = reference.load(tmp_path)

    assert "TOR" in loaded.event_codes
    assert "BAD" not in loaded.event_codes


# Salem, OR and Portland, OR -- roughly 70 km apart great-circle, used below
# as a distance with a known-good answer rather than an arbitrary tolerance.
_SALEM = (44.9429, -123.0351)
_PORTLAND = (45.5152, -122.6784)


def test_haversine_km_matches_a_known_distance():
    distance = reference.haversine_km(*_SALEM, *_PORTLAND)

    assert 68 < distance < 71


def _write_stations(tmp_path, **stations):
    import yaml

    (tmp_path / "nwr_stations_or.yaml").write_text(yaml.safe_dump(stations))


def test_load_stations_computes_distance_from_operator_location(tmp_path):
    _write_stations(
        tmp_path,
        KIG98={
            "name": "Portland",
            "frequency_mhz": 162.550,
            "status": "NORMAL",
            "wfo": "Portland OR",
            "power_watts": 330,
            "lat": _PORTLAND[0],
            "lon": _PORTLAND[1],
        },
    )

    loaded = reference.load(tmp_path, operator_lat=_SALEM[0], operator_lon=_SALEM[1])

    assert 68 < loaded.stations["KIG98"]["distance_km"] < 71


def test_load_stations_without_operator_location_leaves_distance_null(tmp_path):
    _write_stations(
        tmp_path,
        KIG98={
            "name": "Portland",
            "frequency_mhz": 162.550,
            "status": "NORMAL",
            "wfo": "Portland OR",
            "power_watts": 330,
            "lat": _PORTLAND[0],
            "lon": _PORTLAND[1],
        },
    )

    loaded = reference.load(tmp_path)

    assert loaded.stations["KIG98"]["distance_km"] is None


def test_load_stations_with_unknown_station_coordinates_leaves_distance_null(tmp_path):
    """A configured operator location must not make up a distance for a
    station whose own coordinates are unconfirmed (WZ2522/WZ2559 in the
    checked-in data, per data/nwr_stations_or.yaml's header)."""
    _write_stations(
        tmp_path,
        WZ2522={
            "name": "Carney Butte",
            "frequency_mhz": 162.475,
            "status": "NORMAL",
            "wfo": "Pendleton OR",
            "power_watts": None,
            "lat": None,
            "lon": None,
        },
    )

    loaded = reference.load(tmp_path, operator_lat=_SALEM[0], operator_lon=_SALEM[1])

    assert loaded.stations["WZ2522"]["distance_km"] is None
