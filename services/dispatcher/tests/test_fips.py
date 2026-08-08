from dispatcher.fips import FipsEntry, FipsTable


def test_lookup_strips_the_same_subdivision_digit():
    table = FipsTable({"41051": FipsEntry(county="Multnomah", state="OR")})
    assert table.lookup("041051") == FipsEntry(county="Multnomah", state="OR")


def test_lookup_missing_code_returns_none():
    table = FipsTable({"41051": FipsEntry(county="Multnomah", state="OR")})
    assert table.lookup("099999") is None


def test_load_reads_the_checked_in_data_file():
    table = FipsTable.load()
    assert table.lookup("041051") == FipsEntry(county="Multnomah", state="OR")
    assert table.lookup("041005") == FipsEntry(county="Clackamas", state="OR")
