from dispatcher.egress.dispatch import DualPathSender
from dispatcher.egress.meshtastic_node import SendResult


class FakeSerial:
    def __init__(self, result):
        self.result = result
        self.sent = []

    def send_text(self, text):
        self.sent.append(text)
        return self.result


class FakeMqtt:
    def __init__(self, raises=None):
        self.raises = raises
        self.published = []

    def publish_text(self, text):
        self.published.append(text)
        if self.raises:
            raise self.raises


def test_serial_ack_delivers_without_touching_mqtt():
    serial = FakeSerial(SendResult(acked=True, error_reason="NONE"))
    mqtt = FakeMqtt()
    sender = DualPathSender(node_client=serial, mqtt_client=mqtt, mode="hybrid")

    result = sender.send("hello")

    assert result.delivered is True
    assert result.path == "serial"
    assert mqtt.published == []


def test_no_ack_falls_back_to_mqtt_in_hybrid_mode():
    serial = FakeSerial(SendResult(acked=False, error_reason="TIMEOUT"))
    mqtt = FakeMqtt()
    sender = DualPathSender(node_client=serial, mqtt_client=mqtt, mode="hybrid")

    result = sender.send("hello")

    assert result.delivered is True
    assert result.path == "mqtt_fallback"
    assert mqtt.published == ["hello"]


def test_no_ack_does_not_fall_back_to_mqtt_offgrid():
    serial = FakeSerial(SendResult(acked=False, error_reason="TIMEOUT"))
    mqtt = FakeMqtt()
    sender = DualPathSender(node_client=serial, mqtt_client=mqtt, mode="offgrid")

    result = sender.send("hello")

    assert result.delivered is False
    assert result.path == "serial_no_ack"
    assert mqtt.published == []


def test_no_ack_with_no_mqtt_client_configured_even_in_hybrid():
    serial = FakeSerial(SendResult(acked=False, error_reason="TIMEOUT"))
    sender = DualPathSender(node_client=serial, mqtt_client=None, mode="hybrid")

    result = sender.send("hello")

    assert result.delivered is False
    assert result.path == "serial_no_ack"


def test_mqtt_publish_failure_is_reported_not_raised():
    serial = FakeSerial(SendResult(acked=False, error_reason="TIMEOUT"))
    mqtt = FakeMqtt(raises=RuntimeError("broker unreachable"))
    sender = DualPathSender(node_client=serial, mqtt_client=mqtt, mode="hybrid")

    result = sender.send("hello")

    assert result.delivered is False
    assert result.path == "mqtt_fallback_failed"


def test_no_serial_client_reports_mesh_disabled():
    sender = DualPathSender(node_client=None, mqtt_client=None, mode="offgrid")

    result = sender.send("hello")

    assert result.delivered is False
    assert result.path == "mesh_disabled"


def test_no_serial_client_still_relays_over_mqtt_in_hybrid():
    """"No local node, relay via MQTT" is a real deployment -- disabling the
    serial path must not disable the fallback leg with it."""
    mqtt = FakeMqtt()
    sender = DualPathSender(node_client=None, mqtt_client=mqtt, mode="hybrid")

    result = sender.send("hello")

    assert result.delivered is True
    assert result.path == "mqtt_fallback"
    assert mqtt.published == ["hello"]


def test_no_serial_client_offgrid_does_not_touch_mqtt():
    mqtt = FakeMqtt()
    sender = DualPathSender(node_client=None, mqtt_client=mqtt, mode="offgrid")

    assert sender.send("hello").path == "mesh_disabled"
    assert mqtt.published == []


def test_tcp_transport_is_named_in_the_delivered_path():
    """The dispatch log should say which link carried the message, not
    report "serial" for a node reached over the network."""
    node = FakeSerial(SendResult(acked=True, error_reason="NONE"))
    sender = DualPathSender(node_client=node, mqtt_client=None, mode="offgrid", node_transport="tcp")

    assert sender.send("hello").path == "tcp"


def test_tcp_transport_is_named_in_the_no_ack_path():
    node = FakeSerial(SendResult(acked=False, error_reason="TIMEOUT"))
    sender = DualPathSender(node_client=node, mqtt_client=None, mode="offgrid", node_transport="tcp")

    result = sender.send("hello")

    assert result.delivered is False
    assert result.path == "tcp_no_ack"


def test_serial_exception_propagates_uncaught():
    class ExplodingSerial:
        def send_text(self, text):
            raise RuntimeError("serial port gone")

    sender = DualPathSender(node_client=ExplodingSerial(), mqtt_client=FakeMqtt(), mode="hybrid")

    import pytest

    with pytest.raises(RuntimeError, match="serial port gone"):
        sender.send("hello")
