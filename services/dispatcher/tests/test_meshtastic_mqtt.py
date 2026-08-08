import json

from dispatcher.egress.meshtastic_mqtt import MeshtasticMqttClient, TOPIC_TEMPLATE


class FakePublish:
    def __init__(self):
        self.calls = []

    def __call__(self, host, port, topic, payload_json):
        self.calls.append({"host": host, "port": port, "topic": topic, "payload_json": payload_json})


def test_publish_text_uses_the_documented_topic_and_schema():
    fake_publish = FakePublish()
    client = MeshtasticMqttClient(
        host="mosquitto", port=1883, gateway_node_id=2130636288, publish_fn=fake_publish
    )

    client.publish_text("TOR WARN | Multnomah OR | exp 2145Z | RF")

    assert len(fake_publish.calls) == 1
    call = fake_publish.calls[0]
    assert call["host"] == "mosquitto"
    assert call["port"] == 1883
    assert call["topic"] == TOPIC_TEMPLATE.format(region="US")
    payload = json.loads(call["payload_json"])
    assert payload == {
        "from": 2130636288,
        "type": "sendtext",
        "payload": "TOR WARN | Multnomah OR | exp 2145Z | RF",
    }


def test_region_is_configurable():
    fake_publish = FakePublish()
    client = MeshtasticMqttClient(
        host="mosquitto", port=1883, gateway_node_id=1, region="EU_868", publish_fn=fake_publish
    )
    client.publish_text("hello")
    assert fake_publish.calls[0]["topic"] == "msh/EU_868/2/json/mqtt/"


def test_channel_is_included_only_when_given():
    fake_publish = FakePublish()
    client = MeshtasticMqttClient(host="mosquitto", port=1883, gateway_node_id=1, channel=2, publish_fn=fake_publish)
    client.publish_text("hello")
    payload = json.loads(fake_publish.calls[0]["payload_json"])
    assert payload["channel"] == 2
