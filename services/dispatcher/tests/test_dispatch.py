from dispatcher.egress.dispatch import MeshSender
from dispatcher.egress.meshtastic_node import SendResult


class FakeSerial:
    def __init__(self, result):
        self.result = result
        self.sent = []

    def send_text(self, text):
        self.sent.append(text)
        return self.result


def test_serial_ack_delivers():
    serial = FakeSerial(SendResult(acked=True, error_reason="NONE"))
    sender = MeshSender(node_client=serial)

    result = sender.send("hello")

    assert result.delivered is True
    assert result.path == "serial"


def test_no_ack_is_not_delivered():
    serial = FakeSerial(SendResult(acked=False, error_reason="TIMEOUT"))
    sender = MeshSender(node_client=serial)

    result = sender.send("hello")

    assert result.delivered is False
    assert result.path == "serial_no_ack"


def test_no_node_client_reports_mesh_disabled():
    sender = MeshSender(node_client=None)

    result = sender.send("hello")

    assert result.delivered is False
    assert result.path == "mesh_disabled"


def test_tcp_transport_is_named_in_the_delivered_path():
    """The dispatch log should say which link carried the message, not
    report "serial" for a node reached over the network."""
    node = FakeSerial(SendResult(acked=True, error_reason="NONE"))
    sender = MeshSender(node_client=node, node_transport="tcp")

    assert sender.send("hello").path == "tcp"


def test_tcp_transport_is_named_in_the_no_ack_path():
    node = FakeSerial(SendResult(acked=False, error_reason="TIMEOUT"))
    sender = MeshSender(node_client=node, node_transport="tcp")

    result = sender.send("hello")

    assert result.delivered is False
    assert result.path == "tcp_no_ack"


def test_serial_exception_propagates_uncaught():
    class ExplodingSerial:
        def send_text(self, text):
            raise RuntimeError("serial port gone")

    sender = MeshSender(node_client=ExplodingSerial())

    import pytest

    with pytest.raises(RuntimeError, match="serial port gone"):
        sender.send("hello")
