"""Meshtastic MQTT downlink -- injects a text message into the mesh via a
gateway node's own MQTT connection (design doc §7's MQTT fallback leg).

Verified against Meshtastic's real MQTT integration docs this session,
not guessed: publishing JSON to `msh/{region}/2/json/mqtt/` (the design
doc's own literal topic -- confirmed to be exact, not an abbreviation)
instructs a subscribed gateway node to relay a message onto the mesh,
provided that node has a channel literally named "mqtt" configured with
downlink enabled (a device-configuration prerequisite -- see this
service's README, nothing this module can do anything about). JSON
schema: `{"from": <decimal gateway node ID>, "type": "sendtext",
"payload": <text>}`, with an optional `"channel"` (defaults to the
primary channel if omitted).

Uses `paho-mqtt`'s one-shot `publish.single()` (connect, publish,
disconnect) rather than a persistent connection -- this leg only fires
when a serial send didn't get an ack, which is rare by design (design doc
§7: "a hedge against a dead USB cable, not against a grid event"), so
there's no hot path here to justify a long-lived connection's added
failure modes (stale socket, reconnect logic).
"""

from __future__ import annotations

import json
from typing import Callable

DEFAULT_REGION = "US"
TOPIC_TEMPLATE = "msh/{region}/2/json/mqtt/"


def _default_publish(host: str, port: int, topic: str, payload_json: str) -> None:
    import paho.mqtt.publish as mqtt_publish

    mqtt_publish.single(topic, payload=payload_json, hostname=host, port=port)


PublishFn = Callable[[str, int, str, str], None]


class MeshtasticMqttClient:
    def __init__(
        self,
        host: str,
        port: int,
        gateway_node_id: int,
        region: str = DEFAULT_REGION,
        channel: int | None = None,
        publish_fn: PublishFn = _default_publish,
    ):
        self._host = host
        self._port = port
        self._gateway_node_id = gateway_node_id
        self._topic = TOPIC_TEMPLATE.format(region=region)
        self._channel = channel
        self._publish_fn = publish_fn

    def publish_text(self, text: str) -> None:
        payload = {"from": self._gateway_node_id, "type": "sendtext", "payload": text}
        if self._channel is not None:
            payload["channel"] = self._channel
        self._publish_fn(self._host, self._port, self._topic, json.dumps(payload))
