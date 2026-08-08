"""Thin wrapper around the `meshtastic` PyPI package's serial interface
(design doc §7's "Meshtastic dual path"): send stage-1 text, wait up to
15s for an acknowledgment.

The `meshtastic` package talks to real hardware over a serial port and
isn't installed in this authoring sandbox -- same posture as every other
phase's hardware-dependent binding (SoapySDR, multimon-ng, whisper.cpp,
ffmpeg/Icecast): wrap it thinly, make the wrapped call injectable, and
verify the wrapper's own plumbing against a fake rather than the real
library. Confirmed against the library's actual source
(`meshtastic/mesh_interface.py`), not guessed: `sendText`'s `onResponse`
callback fires with a dict whose `decoded["routing"]["errorReason"]` is
`"NONE"` on success and some other string (e.g. `"NO_RESPONSE"`) on
failure -- there is no built-in blocking "wait N seconds for ack"
primitive in the library itself, so this wrapper builds one with a
`threading.Event`, matching the design doc's explicit "wait 15s for ack"
behavior.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

DEFAULT_ACK_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class SendResult:
    acked: bool
    error_reason: str | None


def _default_interface_factory(dev_path: str | None):
    import meshtastic.serial_interface

    return meshtastic.serial_interface.SerialInterface(devPath=dev_path)


class MeshtasticSerialClient:
    def __init__(
        self,
        dev_path: str | None = None,
        interface_factory: Callable[[str | None], object] = _default_interface_factory,
        ack_timeout_seconds: float = DEFAULT_ACK_TIMEOUT_SECONDS,
    ):
        self._interface = interface_factory(dev_path)
        self._ack_timeout_seconds = ack_timeout_seconds

    def send_text(self, text: str) -> SendResult:
        acked_event = threading.Event()
        response: dict = {"error_reason": None}

        def on_response(packet: dict) -> None:
            routing = (packet.get("decoded") or {}).get("routing") or {}
            response["error_reason"] = routing.get("errorReason")
            acked_event.set()

        self._interface.sendText(text, wantAck=True, onResponse=on_response)
        got_response = acked_event.wait(timeout=self._ack_timeout_seconds)
        if not got_response:
            return SendResult(acked=False, error_reason="TIMEOUT")
        return SendResult(acked=response["error_reason"] == "NONE", error_reason=response["error_reason"])

    def close(self) -> None:
        close = getattr(self._interface, "close", None)
        if close is not None:
            close()
