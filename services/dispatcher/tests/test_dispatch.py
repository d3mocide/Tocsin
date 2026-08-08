from dispatcher.egress.dispatch import DualPathSender
from dispatcher.egress.meshtastic_serial import SendResult


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
    sender = DualPathSender(serial_client=serial, mqtt_client=mqtt, mode="hybrid")

    result = sender.send("hello")

    assert result.delivered is True
    assert result.path == "serial"
    assert mqtt.published == []


def test_no_ack_falls_back_to_mqtt_in_hybrid_mode():
    serial = FakeSerial(SendResult(acked=False, error_reason="TIMEOUT"))
    mqtt = FakeMqtt()
    sender = DualPathSender(serial_client=serial, mqtt_client=mqtt, mode="hybrid")

    result = sender.send("hello")

    assert result.delivered is True
    assert result.path == "mqtt_fallback"
    assert mqtt.published == ["hello"]


def test_no_ack_does_not_fall_back_to_mqtt_offgrid():
    serial = FakeSerial(SendResult(acked=False, error_reason="TIMEOUT"))
    mqtt = FakeMqtt()
    sender = DualPathSender(serial_client=serial, mqtt_client=mqtt, mode="offgrid")

    result = sender.send("hello")

    assert result.delivered is False
    assert result.path == "serial_no_ack"
    assert mqtt.published == []


def test_no_ack_with_no_mqtt_client_configured_even_in_hybrid():
    serial = FakeSerial(SendResult(acked=False, error_reason="TIMEOUT"))
    sender = DualPathSender(serial_client=serial, mqtt_client=None, mode="hybrid")

    result = sender.send("hello")

    assert result.delivered is False
    assert result.path == "serial_no_ack"


def test_mqtt_publish_failure_is_reported_not_raised():
    serial = FakeSerial(SendResult(acked=False, error_reason="TIMEOUT"))
    mqtt = FakeMqtt(raises=RuntimeError("broker unreachable"))
    sender = DualPathSender(serial_client=serial, mqtt_client=mqtt, mode="hybrid")

    result = sender.send("hello")

    assert result.delivered is False
    assert result.path == "mqtt_fallback_failed"


def test_serial_exception_propagates_uncaught():
    class ExplodingSerial:
        def send_text(self, text):
            raise RuntimeError("serial port gone")

    sender = DualPathSender(serial_client=ExplodingSerial(), mqtt_client=FakeMqtt(), mode="hybrid")

    import pytest

    with pytest.raises(RuntimeError, match="serial port gone"):
        sender.send("hello")
