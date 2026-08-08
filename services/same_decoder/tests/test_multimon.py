import sys
import time

from same_decoder.multimon import MultimonProcess


def _fake_command(*output_lines: str) -> list[str]:
    """A multimon-ng stand-in: reads 4 bytes (simulating "enough audio came
    in"), prints the given lines, then blocks reading the rest of stdin
    until it's closed -- so MultimonProcess.close()'s stdin.close() drives
    a clean exit, same as it would against the real binary."""
    lines_repr = repr(list(output_lines))
    script = (
        "import sys\n"
        "sys.stdin.buffer.read(4)\n"
        f"for line in {lines_repr}:\n"
        "    print(line, flush=True)\n"
        "sys.stdin.buffer.read()\n"
    )
    return [sys.executable, "-c", script]


def _wait_for_lines(process: MultimonProcess, expected_count: int, timeout: float = 5.0) -> list[str]:
    deadline = time.monotonic() + timeout
    lines: list[str] = []
    while time.monotonic() < deadline and len(lines) < expected_count:
        lines.extend(process.poll_lines())
        if len(lines) < expected_count:
            time.sleep(0.02)
    return lines


def test_write_and_poll_lines_roundtrip():
    process = MultimonProcess(command=_fake_command("EAS: ZCZC-WXR-RWT-018139+0030-0441610-KIND/NWS-"))
    process.write(b"\x00\x00\x00\x00")
    lines = _wait_for_lines(process, 1)
    assert lines == ["EAS: ZCZC-WXR-RWT-018139+0030-0441610-KIND/NWS-"]
    process.close()


def test_multiple_lines_are_all_delivered_in_order():
    process = MultimonProcess(command=_fake_command("EAS: NNNN", "EAS: ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-"))
    process.write(b"\x00\x00\x00\x00")
    lines = _wait_for_lines(process, 2)
    assert lines == ["EAS: NNNN", "EAS: ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-"]
    process.close()


def test_poll_lines_returns_empty_when_nothing_arrived_yet():
    process = MultimonProcess(command=_fake_command("EAS: NNNN"))
    assert process.poll_lines() == []
    process.close()


def test_close_terminates_the_process():
    process = MultimonProcess(command=_fake_command("EAS: NNNN"))
    process.write(b"\x00\x00\x00\x00")
    _wait_for_lines(process, 1)
    process.close()
    assert process._process.poll() is not None
