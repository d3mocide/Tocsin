"""Sends a message over the Meshtastic node (serial or TCP), keyed on
acknowledgment (design doc §7):

    sendText(wantAck=True) over serial/TCP
      -> ack    -> delivered
      -> no ack -> not delivered, logged as such

A `None` node client means no Meshtastic node is attached at all
(`MESHTASTIC_ENABLED=false` -- see `__init__.py`), which is a supported
way to run Tocsin: SAME decode, transcription, the alert log and the web
UI are all independent of the radio, so the whole receive side stays
useful to someone who just wants a monitoring station. Stage 1 still
runs in full -- dedup, idempotency, rate limiting, message building --
so the dispatch log records exactly what *would* have gone out over the
mesh; only the transmit itself is skipped.
"""

from __future__ import annotations

from dataclasses import dataclass

from .meshtastic_node import MeshtasticNodeClient


@dataclass(frozen=True)
class EgressResult:
    delivered: bool
    # "<transport>" | "<transport>_no_ack" | "mesh_disabled", where
    # <transport> is "serial" or "tcp", so the dispatch log says which
    # link actually carried (or dropped) the message.
    path: str


class MeshSender:
    def __init__(self, node_client: MeshtasticNodeClient | None, node_transport: str = "serial"):
        self._node = node_client
        self._node_transport = node_transport

    def send(self, text: str) -> EgressResult:
        if self._node is None:
            return EgressResult(delivered=False, path="mesh_disabled")
        result = self._node.send_text(text)
        if result.acked:
            return EgressResult(delivered=True, path=self._node_transport)
        return EgressResult(delivered=False, path=f"{self._node_transport}_no_ack")
