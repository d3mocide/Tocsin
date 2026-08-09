import pytest

from stt_worker.remote_http import run


class FakeResponse:
    def __init__(self, status_code=200, json_body=None):
        self.status_code = status_code
        self._json_body = json_body or {}

    def json(self):
        return self._json_body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakePost:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, url, headers=None, files=None, data=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "files": files, "data": data, "timeout": timeout})
        return self.response


def test_run_posts_multipart_and_parses_text(tmp_path):
    wav_path = tmp_path / "clip.wav"
    wav_path.write_bytes(b"RIFF....WAVEfmt ")
    fake_post = FakePost(FakeResponse(200, {"text": "a tornado warning"}))

    transcript = run(wav_path, base_url="http://litellm:4000", model="whisper-1", post=fake_post)

    assert transcript.text == "a tornado warning"
    assert transcript.segments == ()
    call = fake_post.calls[0]
    assert call["url"] == "http://litellm:4000/v1/audio/transcriptions"
    assert call["data"] == {"model": "whisper-1"}
    assert "file" in call["files"]


def test_run_sends_mimetypes_guessed_content_type_for_wav(tmp_path):
    """Regression test: a hardcoded `"audio/wav"` content type once caused
    every remote call to fail against a real self-hosted backend that
    didn't recognize that exact string and silently mis-detected the
    upload as mp3 (see `remote_http.py`'s docstring). `mimetypes` maps
    `.wav` to `audio/x-wav` -- matching what openai/httpx (and therefore
    Vertex's own whisper client, confirmed working against the same
    backend) actually send."""
    wav_path = tmp_path / "clip.wav"
    wav_path.write_bytes(b"RIFF....WAVEfmt ")
    fake_post = FakePost(FakeResponse(200, {"text": "ok"}))

    run(wav_path, base_url="http://litellm:4000", post=fake_post)

    _filename, _fileobj, content_type = fake_post.calls[0]["files"]["file"]
    assert content_type == "audio/x-wav"


def test_run_strips_trailing_slash_on_base_url(tmp_path):
    wav_path = tmp_path / "clip.wav"
    wav_path.write_bytes(b"x")
    fake_post = FakePost(FakeResponse(200, {"text": "ok"}))

    run(wav_path, base_url="http://litellm:4000/", post=fake_post)

    assert fake_post.calls[0]["url"] == "http://litellm:4000/v1/audio/transcriptions"


def test_run_sends_bearer_auth_header_when_api_key_given(tmp_path):
    wav_path = tmp_path / "clip.wav"
    wav_path.write_bytes(b"x")
    fake_post = FakePost(FakeResponse(200, {"text": "ok"}))

    run(wav_path, base_url="http://litellm:4000", api_key="sk-test", post=fake_post)

    assert fake_post.calls[0]["headers"]["Authorization"] == "Bearer sk-test"


def test_run_omits_auth_header_when_no_api_key(tmp_path):
    wav_path = tmp_path / "clip.wav"
    wav_path.write_bytes(b"x")
    fake_post = FakePost(FakeResponse(200, {"text": "ok"}))

    run(wav_path, base_url="http://litellm:4000", post=fake_post)

    assert fake_post.calls[0]["headers"] == {}


def test_run_raises_on_http_error(tmp_path):
    wav_path = tmp_path / "clip.wav"
    wav_path.write_bytes(b"x")
    fake_post = FakePost(FakeResponse(500))

    with pytest.raises(RuntimeError):
        run(wav_path, base_url="http://litellm:4000", post=fake_post)


def test_run_handles_missing_text_field(tmp_path):
    wav_path = tmp_path / "clip.wav"
    wav_path.write_bytes(b"x")
    fake_post = FakePost(FakeResponse(200, {}))

    transcript = run(wav_path, base_url="http://litellm:4000", post=fake_post)

    assert transcript.text == ""
