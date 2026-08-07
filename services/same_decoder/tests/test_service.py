import sys
import time

from same_decoder.service import Decoder
from same_decoder.tiers import TierTable

TIERS = TierTable(
    codes={
        "TOR": {"name": "Tornado Warning", "tier": "A"},
        "RWT": {"name": "Required Weekly Test", "tier": "C"},
    }
)


class FakeSink:
    def __init__(self):
        self.events = []

    def record(self, event):
        self.events.append(event)


def _fake_multimon_command(*output_lines: str) -> list[str]:
    lines_repr = repr(list(output_lines))
    script = (
        "import sys\n"
        "sys.stdin.buffer.read(4)\n"
        f"for line in {lines_repr}:\n"
        "    print(line, flush=True)\n"
        "sys.stdin.buffer.read()\n"
    )
    return [sys.executable, "-c", script]


def _wait_for(decoder: Decoder, sink: FakeSink, expected_count: int, feeds: list[tuple[str, str]], timeout: float = 5.0):
    """`Decoder.feed()` only drains multimon-ng's output queue when it's
    called, and the fake subprocess needs a moment to actually write its
    output -- so, like the real main() loop calling feed() continuously as
    audio streams in, keep feeding (silence is fine) until the event(s)
    show up or we time out."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and len(sink.events) < expected_count:
        for site, channel in feeds:
            decoder.feed(site, channel, b"\x00\x00\x00\x00")
        time.sleep(0.02)
    return sink.events


def test_feed_emits_a_tiered_event_from_a_decoded_line():
    sink = FakeSink()
    decoder = Decoder(
        TIERS,
        sink=sink,
        multimon_command=_fake_multimon_command("EAS: ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-"),
    )
    events = _wait_for(decoder, sink, 1, feeds=[("home", "WX5")])

    assert len(events) == 1
    event = events[0]
    assert event.site == "home"
    assert event.channel == "WX5"
    assert event.event_code == "TOR"
    assert event.event_name == "Tornado Warning"
    assert event.tier == "A"
    assert event.fips_codes == ("017021",)

    decoder.close()


def test_feed_ignores_lines_that_do_not_parse():
    sink = FakeSink()
    decoder = Decoder(TIERS, sink=sink, multimon_command=_fake_multimon_command("EAS: NNNN"))
    for _ in range(10):
        decoder.feed("home", "WX5", b"\x00\x00\x00\x00")
        time.sleep(0.02)
    assert sink.events == []
    decoder.close()


def test_repeated_identical_header_is_deduplicated():
    sink = FakeSink()
    line = "EAS: ZCZC-WXR-RWT-018139+0030-0441610-KIND/NWS-"
    decoder = Decoder(TIERS, sink=sink, multimon_command=_fake_multimon_command(line, line))
    _wait_for(decoder, sink, 1, feeds=[("home", "WX5")])
    # give a second poll window a chance to pick up the (deduplicated) repeat
    time.sleep(0.2)
    decoder.feed("home", "WX5", b"\x00\x00\x00\x00")
    assert len(sink.events) == 1
    decoder.close()


def test_different_channels_get_independent_multimon_processes():
    sink = FakeSink()
    decoder = Decoder(
        TIERS,
        sink=sink,
        multimon_command=_fake_multimon_command("EAS: ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-"),
    )
    events = _wait_for(decoder, sink, 2, feeds=[("home", "WX5"), ("home", "WX1")])

    assert {(e.site, e.channel) for e in events} == {("home", "WX5"), ("home", "WX1")}
    decoder.close()
