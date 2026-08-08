"""Subprocess wrapper around `multimon-ng -t raw -a EAS -` (design doc §4).

Identical in shape to `same_decoder.multimon` -- both services independently
run their own multimon-ng instance against the same `same.<site>.<channel>`
audio (see `subscriber.py`), rather than one depending on the other's
output, so either can be restarted without the other (design doc §2's "one
process owns the dongle... independently restartable" invariant, applied to
this pair of siblings too). Duplicated rather than imported across the
service boundary (CLAUDE.md).

The command is injectable so this is testable without multimon-ng actually
installed -- tests substitute a small stand-in script.
"""

from __future__ import annotations

import subprocess
import threading
from queue import Empty, Queue

DEFAULT_COMMAND = ["multimon-ng", "-t", "raw", "-a", "EAS", "-"]


class MultimonProcess:
    """One running multimon-ng subprocess, e.g. one per (site, channel).

    Owns a background thread draining stdout into a queue: multimon-ng can
    emit a decoded line at any point relative to when audio is written, so
    polling write/read in lockstep would risk deadlocking on multimon-ng's
    internal buffering.
    """

    def __init__(self, command: list[str] | None = None):
        self._process = subprocess.Popen(
            command or DEFAULT_COMMAND,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        self._lines: Queue[str] = Queue()
        self._reader = threading.Thread(target=self._drain_stdout, daemon=True)
        self._reader.start()

    def _drain_stdout(self) -> None:
        assert self._process.stdout is not None
        for raw_line in self._process.stdout:
            self._lines.put(raw_line.decode(errors="replace").rstrip("\n"))

    def write(self, pcm_bytes: bytes) -> None:
        assert self._process.stdin is not None
        self._process.stdin.write(pcm_bytes)
        self._process.stdin.flush()

    def poll_lines(self) -> list[str]:
        """Non-blocking: drain and return whatever decoded lines have
        arrived since the last call."""
        lines = []
        while True:
            try:
                lines.append(self._lines.get_nowait())
            except Empty:
                break
        return lines

    def close(self) -> None:
        if self._process.stdin is not None:
            try:
                self._process.stdin.close()
            except OSError:
                pass
        self._process.terminate()
        try:
            self._process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
        self._reader.join(timeout=2.0)
