"""Node-primary, MQTT-fallback dual path, keyed on acknowledgment rather
than connection state (design doc §7):

    sendText(wantAck=True) over serial/TCP
      -> wait 15s for ack
           ack    -> delivered, done
           no ack -> publish to msh/.../json/mqtt/ (hybrid only)
      -> mark delivered

MQTT fallback is gated on `TOCSIN_MODE=hybrid` -- design doc §8's
connectivity contract lists "Meshtastic MQTT fallback" as one of exactly
four network-dependent components disabled under `offgrid`. `dispatcher`
is the second service in this repo (after `fusion`) to actually read
`TOCSIN_MODE` in code rather than only via compose profile selection,
since stage 1's serial path itself has no mode dependency at all.

A `None` serial client means no Meshtastic node is attached at all
(`MESHTASTIC_ENABLED=false` -- see `__init__.py`), which is a supported
way to run Tocsin: SAME decode, transcription, the alert log and the web
UI are all independent of the radio, so the whole receive side stays
useful to someone who just wants a monitoring station. Stage 1 still
runs in full -- dedup, idempotency, rate limiting, message building --
so the dispatch log records exactly what *would* have gone out over the
mesh; only the transmit itself is skipped. Note this still leaves the
MQTT leg reachable in hybrid mode: "no local node, relay via MQTT" is a
real deployment, not a contradiction.

Once the MQTT publish is *attempted*, this marks the message delivered
regardless of further confirmation -- there's no ack tracking for the
MQTT leg itself (design doc's own flow: "no ack -> publish... -> mark
delivered"). Deliberately fire-and-forget, not a second guarantee layered
on top of the first.
"""

from __future__ import annotations

from dataclasses import dataclass

from .meshtastic_mqtt import MeshtasticMqttClient
from .meshtastic_node import MeshtasticNodeClient

HYBRID_MODE = "hybrid"


@dataclass(frozen=True)
class EgressResult:
    delivered: bool
    # "<transport>" | "<transport>_no_ack" | "mesh_disabled"
    # | "mqtt_fallback" | "mqtt_fallback_failed"
    # ...where <transport> is "serial" or "tcp", so the dispatch log says
    # which link actually carried (or dropped) the message.
    path: str


class DualPathSender:
    def __init__(
        self,
        node_client: MeshtasticNodeClient | None,
        mqtt_client: MeshtasticMqttClient | None,
        mode: str,
        node_transport: str = "serial",
    ):
        self._node = node_client
        self._mqtt = mqtt_client
        self._mode = mode
        self._node_transport = node_transport

    def send(self, text: str) -> EgressResult:
        if self._node is None:
            unsent_path = "mesh_disabled"
        else:
            result = self._node.send_text(text)
            if result.acked:
                return EgressResult(delivered=True, path=self._node_transport)
            unsent_path = f"{self._node_transport}_no_ack"

        if self._mode != HYBRID_MODE or self._mqtt is None:
            return EgressResult(delivered=False, path=unsent_path)

        try:
            self._mqtt.publish_text(text)
        except Exception:
            return EgressResult(delivered=False, path="mqtt_fallback_failed")
        return EgressResult(delivered=True, path="mqtt_fallback")
