from datetime import datetime, timezone

from dispatcher.fips import FipsEntry, FipsTable
from dispatcher.message import MAX_BYTES, build_stage1_message

FIPS_TABLE = FipsTable(
    {
        "41051": FipsEntry(county="Multnomah", state="OR"),
        "41005": FipsEntry(county="Clackamas", state="OR"),
    }
)


def test_matches_the_design_docs_own_example():
    message = build_stage1_message(
        event_code="TOR",
        fips_codes=("041051", "041005"),
        purge_minutes=45,
        received_at=datetime(2026, 8, 8, 21, 0, tzinfo=timezone.utc),
        fips_table=FIPS_TABLE,
    )
    assert message == "TOR WARN | Multnomah,Clackamas OR | exp 2145Z | RF"


def test_unknown_fips_falls_back_to_the_raw_code():
    message = build_stage1_message(
        event_code="SVR",
        fips_codes=("099999",),
        purge_minutes=30,
        received_at=datetime(2026, 8, 8, 21, 0, tzinfo=timezone.utc),
        fips_table=FIPS_TABLE,
    )
    assert "099999" in message
    assert message.startswith("SVR WARN | 099999")


def test_single_county_has_no_stray_state_prefix_comma():
    message = build_stage1_message(
        event_code="TOR",
        fips_codes=("041051",),
        purge_minutes=45,
        received_at=datetime(2026, 8, 8, 21, 0, tzinfo=timezone.utc),
        fips_table=FIPS_TABLE,
    )
    assert message == "TOR WARN | Multnomah OR | exp 2145Z | RF"


def test_message_never_exceeds_the_byte_budget_even_with_many_counties():
    # SAME allows up to 31 FIPS codes; 6-digit PSSCCC (P=0, SSCCC=plain FIPS).
    plain_fips = [f"{41000 + n:05d}" for n in range(3, 3 + 31)]
    many_fips = tuple(f"0{code}" for code in plain_fips)
    table = FipsTable({code: FipsEntry(county=f"County{code}", state="OR") for code in plain_fips})

    message = build_stage1_message(
        event_code="TOR",
        fips_codes=many_fips,
        purge_minutes=45,
        received_at=datetime(2026, 8, 8, 21, 0, tzinfo=timezone.utc),
        fips_table=table,
    )

    assert len(message.encode("ascii")) <= MAX_BYTES
    assert message.endswith("...")


def test_purge_minutes_is_an_offset_added_to_received_at():
    message = build_stage1_message(
        event_code="TOR",
        fips_codes=("041051",),
        purge_minutes=15,
        received_at=datetime(2026, 8, 8, 23, 50, tzinfo=timezone.utc),
        fips_table=FIPS_TABLE,
    )
    assert "exp 0005Z" in message  # 23:50 + 15min = 00:05 next day
