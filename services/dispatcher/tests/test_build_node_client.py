import pytest

import dispatcher


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        "MESHTASTIC_ENABLED",
        "MESHTASTIC_TRANSPORT",
        "MESHTASTIC_TCP_HOST",
        "MESHTASTIC_TCP_PORT",
        "MESHTASTIC_SERIAL_DEV_PATH",
        "MESHTASTIC_CHANNEL_INDEX",
    ):
        monkeypatch.delenv(var, raising=False)


def _capture_client(monkeypatch):
    """Replaces the client with one that records the interface factory it was
    handed, without ever building a real interface."""
    seen = {}

    def fake_client(factory, channel_index=None):
        seen["factory"] = factory
        seen["channel_index"] = channel_index
        return "client"

    monkeypatch.setattr(dispatcher, "MeshtasticNodeClient", fake_client)
    return seen


@pytest.mark.parametrize("value", ["false", "False", "FALSE", "0", "no", "off", " false "])
def test_mesh_disabled_returns_no_client(monkeypatch, value):
    monkeypatch.setenv("MESHTASTIC_ENABLED", value)

    assert dispatcher._build_node_client("serial") is None


def test_defaults_to_enabled_when_unset(monkeypatch):
    """Absent env var must keep the pre-existing behaviour -- relaying to
    the mesh is the point of the project, so opting out is explicit."""
    _capture_client(monkeypatch)

    assert dispatcher._build_node_client("serial") == "client"


def test_channel_index_defaults_to_none(monkeypatch):
    """Unset MESHTASTIC_CHANNEL_INDEX forwards None -- MeshtasticNodeClient
    itself substitutes the Primary channel, not this function."""
    seen = _capture_client(monkeypatch)

    dispatcher._build_node_client("serial")

    assert seen["channel_index"] is None


def test_channel_index_is_passed_through(monkeypatch):
    monkeypatch.setenv("MESHTASTIC_CHANNEL_INDEX", "3")
    seen = _capture_client(monkeypatch)

    dispatcher._build_node_client("serial")

    assert seen["channel_index"] == 3


def test_serial_dev_path_is_passed_through(monkeypatch):
    monkeypatch.setenv("MESHTASTIC_SERIAL_DEV_PATH", "/dev/ttyACM0")
    seen = _capture_client(monkeypatch)
    built = {}
    monkeypatch.setattr(
        dispatcher,
        "serial_interface_factory",
        lambda dev_path=None: built.setdefault("dev_path", dev_path),
    )

    dispatcher._build_node_client("serial")

    assert built["dev_path"] == "/dev/ttyACM0"
    assert "factory" in seen


def test_tcp_uses_host_and_default_port(monkeypatch):
    monkeypatch.setenv("MESHTASTIC_TCP_HOST", "192.168.1.50")
    _capture_client(monkeypatch)
    built = {}
    monkeypatch.setattr(
        dispatcher,
        "tcp_interface_factory",
        lambda host, port: built.update(host=host, port=port),
    )

    dispatcher._build_node_client("tcp")

    assert built == {"host": "192.168.1.50", "port": 4403}


def test_tcp_port_override(monkeypatch):
    monkeypatch.setenv("MESHTASTIC_TCP_HOST", "node.lan")
    monkeypatch.setenv("MESHTASTIC_TCP_PORT", "14403")
    _capture_client(monkeypatch)
    built = {}
    monkeypatch.setattr(
        dispatcher,
        "tcp_interface_factory",
        lambda host, port: built.update(host=host, port=port),
    )

    dispatcher._build_node_client("tcp")

    assert built == {"host": "node.lan", "port": 14403}


def test_tcp_without_host_is_fatal(monkeypatch):
    """A TCP node with nowhere to dial is a misconfiguration, not a reason
    to silently fall back to serial."""
    with pytest.raises(SystemExit) as excinfo:
        dispatcher._build_node_client("tcp")

    assert excinfo.value.code == 1


def test_unreachable_node_is_fatal_when_mesh_enabled(monkeypatch):
    """A configured-but-missing node stays a loud exit 1 -- only an
    explicit MESHTASTIC_ENABLED=false makes an absent node acceptable."""

    def explode(factory):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(dispatcher, "MeshtasticNodeClient", explode)

    with pytest.raises(SystemExit) as excinfo:
        dispatcher._build_node_client("serial")

    assert excinfo.value.code == 1


@pytest.mark.parametrize("value", ["serial", "tcp", "TCP", " tcp "])
def test_transport_accepts_known_values(monkeypatch, value):
    monkeypatch.setenv("MESHTASTIC_TRANSPORT", value)

    assert dispatcher._node_transport() == value.strip().lower()


def test_transport_defaults_to_serial():
    assert dispatcher._node_transport() == "serial"


def test_unknown_transport_is_fatal(monkeypatch):
    monkeypatch.setenv("MESHTASTIC_TRANSPORT", "bluetooth")

    with pytest.raises(SystemExit) as excinfo:
        dispatcher._node_transport()

    assert excinfo.value.code == 1
