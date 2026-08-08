import threading

from dispatcher.meshtastic_serial import MeshtasticSerialClient


class FakeInterfaceAcksImmediately:
    def __init__(self, error_reason="NONE"):
        self.error_reason = error_reason
        self.sent = []

    def sendText(self, text, wantAck=None, onResponse=None):
        self.sent.append(text)
        onResponse({"decoded": {"routing": {"errorReason": self.error_reason}}})

    def close(self):
        self.closed = True


class FakeInterfaceNeverResponds:
    def sendText(self, text, wantAck=None, onResponse=None):
        pass  # simulates no ack arriving before the timeout


class FakeInterfaceRespondsOnAThread:
    """Exercises the real threading.Event wait path, not just a
    synchronous callback -- meshtastic-python's onResponse genuinely fires
    from a background thread in real use."""

    def sendText(self, text, wantAck=None, onResponse=None):
        def fire():
            onResponse({"decoded": {"routing": {"errorReason": "NONE"}}})

        threading.Timer(0.01, fire).start()


def _client(interface):
    return MeshtasticSerialClient(interface_factory=lambda dev_path: interface, ack_timeout_seconds=1.0)


def test_ack_success():
    result = _client(FakeInterfaceAcksImmediately()).send_text("hello")
    assert result.acked is True
    assert result.error_reason == "NONE"


def test_nak_is_not_acked():
    result = _client(FakeInterfaceAcksImmediately(error_reason="NO_RESPONSE")).send_text("hello")
    assert result.acked is False
    assert result.error_reason == "NO_RESPONSE"


def test_no_response_times_out():
    client = MeshtasticSerialClient(
        interface_factory=lambda dev_path: FakeInterfaceNeverResponds(),
        ack_timeout_seconds=0.05,
    )
    result = client.send_text("hello")
    assert result.acked is False
    assert result.error_reason == "TIMEOUT"


def test_response_from_a_background_thread_is_observed():
    result = _client(FakeInterfaceRespondsOnAThread()).send_text("hello")
    assert result.acked is True


def test_close_delegates_to_the_interface():
    interface = FakeInterfaceAcksImmediately()
    client = _client(interface)
    client.close()
    assert interface.closed is True


def test_send_text_passes_the_message_through():
    interface = FakeInterfaceAcksImmediately()
    _client(interface).send_text("TOR WARN | Multnomah OR | exp 2145Z | RF")
    assert interface.sent == ["TOR WARN | Multnomah OR | exp 2145Z | RF"]
