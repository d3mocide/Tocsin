"""Thin wrapper around the `meshtastic` PyPI package's node interfaces
(design doc §7's "Meshtastic dual path": `sendText(wantAck=True)` over
**serial/TCP**): send stage-1 text, wait up to 15s for an acknowledgment.

Two transports, one client. `SerialInterface` and `TCPInterface` both
derive from `MeshInterface` and expose identical `sendText`/`close`, so
the ack-waiting logic here is transport-agnostic and only the factory
differs -- which is why this generalizes to a `interface_factory` seam
rather than two near-duplicate classes (CLAUDE.md: generalize once there
are two real implementations, not before).

Confirmed against the installed library's actual signatures, not guessed:
`SerialInterface(devPath=None, ...)` and `TCPInterface(hostname, ...,
portNumber=4403)`. Likewise `sendText`'s `onResponse` callback fires with
a dict whose `decoded["routing"]["errorReason"]` is `"NONE"` on success
and some other string (e.g. `"NO_RESPONSE"`) on failure -- there is no
built-in blocking "wait N seconds for ack" primitive in the library
itself, so this wrapper builds one with a `threading.Event`, matching the
design doc's explicit "wait 15s for ack" behavior.

A TCP node is *not* an internet dependency and stays valid in `offgrid`:
it is a node on the local network (Ethernet/WiFi) rather than on a USB
cable. Design doc §8's four network-gated components do not include the
link to your own node -- the MQTT *fallback* leg is the mode-gated one,
because that one genuinely needs an internet-connected gateway.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

DEFAULT_ACK_TIMEOUT_SECONDS = 15.0
DEFAULT_TCP_PORT = 4403

InterfaceFactory = Callable[[], object]


@dataclass(frozen=True)
class SendResult:
    acked: bool
    error_reason: str | None


def serial_interface_factory(dev_path: str | None = None) -> InterfaceFactory:
    """`dev_path=None` -> meshtastic-python autodetects the device; set it
    explicitly when more than one serial device is attached."""

    def build():
        import meshtastic.serial_interface

        return meshtastic.serial_interface.SerialInterface(devPath=dev_path)

    return build


def tcp_interface_factory(host: str, port: int = DEFAULT_TCP_PORT) -> InterfaceFactory:
    def build():
        import meshtastic.tcp_interface

        return meshtastic.tcp_interface.TCPInterface(hostname=host, portNumber=port)

    return build


class MeshtasticNodeClient:
    def __init__(
        self,
        interface_factory: InterfaceFactory,
        ack_timeout_seconds: float = DEFAULT_ACK_TIMEOUT_SECONDS,
    ):
        self._interface = interface_factory()
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
