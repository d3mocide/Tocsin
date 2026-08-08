import pytest

import dispatcher


@pytest.mark.parametrize("value", ["false", "False", "FALSE", "0", "no", "off", " false "])
def test_mesh_disabled_returns_no_client(monkeypatch, value):
    monkeypatch.setenv("MESHTASTIC_ENABLED", value)

    assert dispatcher._build_serial_client() is None


@pytest.mark.parametrize("value", ["true", "1", "yes", "anything-else"])
def test_mesh_enabled_builds_client(monkeypatch, value):
    monkeypatch.setenv("MESHTASTIC_ENABLED", value)
    monkeypatch.setattr(dispatcher, "MeshtasticSerialClient", lambda dev_path=None: f"client:{dev_path}")

    assert dispatcher._build_serial_client() == "client:None"


def test_defaults_to_enabled_when_unset(monkeypatch):
    """Absent env var must keep the pre-existing behaviour -- relaying to
    the mesh is the point of the project, so opting out is explicit."""
    monkeypatch.delenv("MESHTASTIC_ENABLED", raising=False)
    monkeypatch.setattr(dispatcher, "MeshtasticSerialClient", lambda dev_path=None: "client")

    assert dispatcher._build_serial_client() == "client"


def test_dev_path_is_passed_through(monkeypatch):
    monkeypatch.setenv("MESHTASTIC_ENABLED", "true")
    monkeypatch.setenv("MESHTASTIC_SERIAL_DEV_PATH", "/dev/ttyACM0")
    monkeypatch.setattr(dispatcher, "MeshtasticSerialClient", lambda dev_path=None: f"client:{dev_path}")

    assert dispatcher._build_serial_client() == "client:/dev/ttyACM0"


def test_unopenable_node_is_fatal_when_mesh_enabled(monkeypatch):
    """A configured-but-missing node stays a loud exit 1 -- only an
    explicit MESHTASTIC_ENABLED=false makes an absent node acceptable."""
    monkeypatch.setenv("MESHTASTIC_ENABLED", "true")

    def explode(dev_path=None):
        raise RuntimeError("no such device")

    monkeypatch.setattr(dispatcher, "MeshtasticSerialClient", explode)

    with pytest.raises(SystemExit) as excinfo:
        dispatcher._build_serial_client()

    assert excinfo.value.code == 1
