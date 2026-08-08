"""Serial-primary, MQTT-fallback dual path, keyed on acknowledgment rather
than connection state (design doc §7):

    sendText(wantAck=True) over serial
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

Once the MQTT publish is *attempted*, this marks the message delivered
regardless of further confirmation -- there's no ack tracking for the
MQTT leg itself (design doc's own flow: "no ack -> publish... -> mark
delivered"). Deliberately fire-and-forget, not a second guarantee layered
on top of the first.
"""

from __future__ import annotations

from dataclasses import dataclass

from .meshtastic_mqtt import MeshtasticMqttClient
from .meshtastic_serial import MeshtasticSerialClient

HYBRID_MODE = "hybrid"


@dataclass(frozen=True)
class EgressResult:
    delivered: bool
    path: str  # "serial" | "mqtt_fallback" | "serial_no_ack" | "mqtt_fallback_failed"


class DualPathSender:
    def __init__(
        self,
        serial_client: MeshtasticSerialClient,
        mqtt_client: MeshtasticMqttClient | None,
        mode: str,
    ):
        self._serial = serial_client
        self._mqtt = mqtt_client
        self._mode = mode

    def send(self, text: str) -> EgressResult:
        result = self._serial.send_text(text)
        if result.acked:
            return EgressResult(delivered=True, path="serial")

        if self._mode != HYBRID_MODE or self._mqtt is None:
            return EgressResult(delivered=False, path="serial_no_ack")

        try:
            self._mqtt.publish_text(text)
        except Exception:
            return EgressResult(delivered=False, path="mqtt_fallback_failed")
        return EgressResult(delivered=True, path="mqtt_fallback")
