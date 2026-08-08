import dispatcher
from dispatcher.litellm_client import DEFAULT_MODEL


def test_stage2_disabled_without_base_url(monkeypatch):
    monkeypatch.delenv("DISPATCHER_LITELLM_BASE_URL", raising=False)

    assert dispatcher._build_stage2_dispatcher(object(), object(), None) is None


def test_litellm_client_uses_model_from_env(monkeypatch):
    monkeypatch.setenv("DISPATCHER_LITELLM_BASE_URL", "http://litellm:4000")
    monkeypatch.setenv("DISPATCHER_LITELLM_MODEL", "claude-sonnet-4-5")
    monkeypatch.setenv("DISPATCHER_LITELLM_API_KEY", "sk-test")
    captured = {}

    def fake_client(base_url, api_key=None, model=None):
        captured.update(base_url=base_url, api_key=api_key, model=model)

    monkeypatch.setattr(dispatcher, "LiteLLMClient", fake_client)

    dispatcher._build_stage2_dispatcher(object(), object(), None)

    assert captured["model"] == "claude-sonnet-4-5"
    assert captured["base_url"] == "http://litellm:4000"
    assert captured["api_key"] == "sk-test"


def test_litellm_client_falls_back_to_default_model(monkeypatch):
    monkeypatch.setenv("DISPATCHER_LITELLM_BASE_URL", "http://litellm:4000")
    monkeypatch.delenv("DISPATCHER_LITELLM_MODEL", raising=False)
    captured = {}

    def fake_client(base_url, api_key=None, model=None):
        captured.update(model=model)

    monkeypatch.setattr(dispatcher, "LiteLLMClient", fake_client)

    dispatcher._build_stage2_dispatcher(object(), object(), None)

    assert captured["model"] == DEFAULT_MODEL
