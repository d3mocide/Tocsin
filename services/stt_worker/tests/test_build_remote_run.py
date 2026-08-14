import stt_worker
from stt_worker import remote_http


def _enable_remote(monkeypatch):
    monkeypatch.setenv("STT_CHAIN", "local,remote")
    monkeypatch.setenv("STT_WORKER_REMOTE_BASE_URL", "http://litellm:4000")


def test_remote_run_uses_model_from_env(monkeypatch, tmp_path):
    _enable_remote(monkeypatch)
    monkeypatch.setenv("STT_WORKER_REMOTE_MODEL", "Systran/faster-whisper-large-v3")
    captured = {}

    def fake_run(wav_path, base_url, api_key=None, model=None):
        captured.update(base_url=base_url, api_key=api_key, model=model)

    monkeypatch.setattr(remote_http, "run", fake_run)

    stt_worker._build_remote_run(stt_worker.parse_chain("local,remote"))(tmp_path / "clip.wav")

    assert captured["model"] == "Systran/faster-whisper-large-v3"
    assert captured["base_url"] == "http://litellm:4000"


def test_remote_run_falls_back_to_default_model(monkeypatch, tmp_path):
    _enable_remote(monkeypatch)
    monkeypatch.delenv("STT_WORKER_REMOTE_MODEL", raising=False)
    captured = {}

    def fake_run(wav_path, base_url, api_key=None, model=None):
        captured.update(model=model)

    monkeypatch.setattr(remote_http, "run", fake_run)

    stt_worker._build_remote_run(stt_worker.parse_chain("local,remote"))(tmp_path / "clip.wav")

    assert captured["model"] == remote_http.DEFAULT_MODEL


def test_parse_chain_defaults_to_local():
    assert stt_worker.parse_chain(None) == {"local"}
    assert stt_worker.parse_chain("") == {"local"}
    assert stt_worker.parse_chain("  ") == {"local"}


def test_parse_chain_accepts_remote_only():
    """A hybrid box transcribing entirely against a remote endpoint: no
    local provider, so nothing waits for a ggml model that will never be
    staged."""
    assert stt_worker.parse_chain("remote") == {"remote"}
    assert stt_worker.parse_chain(" local , remote ") == {"local", "remote"}


def test_remote_is_disabled_without_a_base_url(monkeypatch):
    monkeypatch.delenv("STT_WORKER_REMOTE_BASE_URL", raising=False)
    assert stt_worker._build_remote_run({"local", "remote"}) is None


def test_build_keyword_matcher_loads_real_checked_in_table(monkeypatch):
    monkeypatch.delenv("TOCSIN_DATA_DIR", raising=False)
    matcher = stt_worker._build_keyword_matcher()
    assert matcher is not None
    assert matcher.match("a tornado warning has been issued").event_code == "TOR"


def test_build_keyword_matcher_degrades_gracefully_on_missing_file(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TOCSIN_DATA_DIR", str(tmp_path))  # empty dir -- no data files -> OSError
    matcher = stt_worker._build_keyword_matcher()
    assert matcher is None
    assert "could not load keyword trigger table" in capsys.readouterr().err


def test_build_keyword_matcher_degrades_gracefully_on_unresolvable_data_dir(monkeypatch, capsys):
    """An unset TOCSIN_DATA_DIR inside a flattened Docker tree makes the
    loader's own default-dir inference raise RuntimeError, not OSError
    (see keyword_match._default_data_dir) -- this must not crash-loop the
    whole worker over a supplementary detection path."""
    import stt_worker.keyword_match as keyword_match_module

    monkeypatch.delenv("TOCSIN_DATA_DIR", raising=False)

    def raise_runtime_error(module_file=__file__):
        raise RuntimeError("can't infer a default data/ directory")

    monkeypatch.setattr(keyword_match_module, "_default_data_dir", raise_runtime_error)

    matcher = stt_worker._build_keyword_matcher()
    assert matcher is None
    assert "could not load keyword trigger table" in capsys.readouterr().err
