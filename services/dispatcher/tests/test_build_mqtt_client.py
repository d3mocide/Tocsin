import pytest

import dispatcher


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("MESHTASTIC_GATEWAY_NODE_ID", "MESHTASTIC_CHANNEL_INDEX"):
        monkeypatch.delenv(var, raising=False)


def _capture_client(monkeypatch):
    seen = {}

    def fake_client(**kwargs):
        seen.update(kwargs)
        return "client"

    monkeypatch.setattr(dispatcher, "MeshtasticMqttClient", fake_client)
    return seen


def test_no_gateway_node_id_returns_none(monkeypatch):
    assert dispatcher._build_mqtt_client() is None


def test_channel_defaults_to_none(monkeypatch):
    monkeypatch.setenv("MESHTASTIC_GATEWAY_NODE_ID", "1")
    seen = _capture_client(monkeypatch)

    dispatcher._build_mqtt_client()

    assert seen["channel"] is None


def test_channel_is_passed_through(monkeypatch):
    monkeypatch.setenv("MESHTASTIC_GATEWAY_NODE_ID", "1")
    monkeypatch.setenv("MESHTASTIC_CHANNEL_INDEX", "3")
    seen = _capture_client(monkeypatch)

    dispatcher._build_mqtt_client()

    assert seen["channel"] == 3
