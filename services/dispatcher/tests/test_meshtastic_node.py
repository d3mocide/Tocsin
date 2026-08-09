import threading

from dispatcher.egress.meshtastic_node import MeshtasticNodeClient


class FakeInterfaceAcksImmediately:
    def __init__(self, error_reason="NONE"):
        self.error_reason = error_reason
        self.sent = []
        self.channel_indices = []

    def sendText(self, text, wantAck=None, onResponse=None, channelIndex=None):
        self.sent.append(text)
        self.channel_indices.append(channelIndex)
        onResponse({"decoded": {"routing": {"errorReason": self.error_reason}}})

    def close(self):
        self.closed = True


class FakeInterfaceNeverResponds:
    def sendText(self, text, wantAck=None, onResponse=None, channelIndex=None):
        pass  # simulates no ack arriving before the timeout


class FakeInterfaceRespondsOnAThread:
    """Exercises the real threading.Event wait path, not just a
    synchronous callback -- meshtastic-python's onResponse genuinely fires
    from a background thread in real use."""

    def sendText(self, text, wantAck=None, onResponse=None, channelIndex=None):
        def fire():
            onResponse({"decoded": {"routing": {"errorReason": "NONE"}}})

        threading.Timer(0.01, fire).start()


def _client(interface):
    return MeshtasticNodeClient(interface_factory=lambda: interface, ack_timeout_seconds=1.0)


def test_ack_success():
    result = _client(FakeInterfaceAcksImmediately()).send_text("hello")
    assert result.acked is True
    assert result.error_reason == "NONE"


def test_nak_is_not_acked():
    result = _client(FakeInterfaceAcksImmediately(error_reason="NO_RESPONSE")).send_text("hello")
    assert result.acked is False
    assert result.error_reason == "NO_RESPONSE"


def test_no_response_times_out():
    client = MeshtasticNodeClient(
        interface_factory=lambda: FakeInterfaceNeverResponds(),
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


def test_default_channel_index_is_zero():
    interface = FakeInterfaceAcksImmediately()
    _client(interface).send_text("hello")
    assert interface.channel_indices == [0]


def test_channel_index_is_configurable():
    interface = FakeInterfaceAcksImmediately()
    client = MeshtasticNodeClient(
        interface_factory=lambda: interface, ack_timeout_seconds=1.0, channel_index=3
    )
    client.send_text("hello")
    assert interface.channel_indices == [3]
