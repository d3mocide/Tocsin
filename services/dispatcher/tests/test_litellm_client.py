import pytest

from dispatcher.litellm_client import LiteLLMClient


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

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return self.response


def _chat_response(content):
    return FakeResponse(200, {"choices": [{"message": {"content": content}}]})


def test_compress_posts_openai_shaped_chat_completion_request():
    fake_post = FakePost(_chat_response("Flash flooding possible."))
    client = LiteLLMClient(base_url="http://litellm:4000", model="gpt-4o-mini", post=fake_post)

    result = client.compress("a long transcript about flooding", max_bytes=200)

    assert result == "Flash flooding possible."
    call = fake_post.calls[0]
    assert call["url"] == "http://litellm:4000/chat/completions"
    assert call["json"]["model"] == "gpt-4o-mini"
    assert call["json"]["messages"][1]["content"] == "a long transcript about flooding"
    assert call["timeout"] == 3.0


def test_compress_strips_trailing_slash_on_base_url():
    fake_post = FakePost(_chat_response("ok"))
    client = LiteLLMClient(base_url="http://litellm:4000/", post=fake_post)
    client.compress("text", max_bytes=200)
    assert fake_post.calls[0]["url"] == "http://litellm:4000/chat/completions"


def test_compress_sends_bearer_auth_when_api_key_given():
    fake_post = FakePost(_chat_response("ok"))
    client = LiteLLMClient(base_url="http://litellm:4000", api_key="sk-test", post=fake_post)
    client.compress("text", max_bytes=200)
    assert fake_post.calls[0]["headers"]["Authorization"] == "Bearer sk-test"


def test_compress_omits_auth_header_without_api_key():
    fake_post = FakePost(_chat_response("ok"))
    client = LiteLLMClient(base_url="http://litellm:4000", post=fake_post)
    client.compress("text", max_bytes=200)
    assert "Authorization" not in fake_post.calls[0]["headers"]


def test_compress_strips_whitespace_from_response():
    fake_post = FakePost(_chat_response("  Flash flooding possible.  \n"))
    client = LiteLLMClient(base_url="http://litellm:4000", post=fake_post)
    assert client.compress("text", max_bytes=200) == "Flash flooding possible."


def test_compress_raises_on_http_error():
    fake_post = FakePost(FakeResponse(500))
    client = LiteLLMClient(base_url="http://litellm:4000", post=fake_post)
    with pytest.raises(RuntimeError):
        client.compress("text", max_bytes=200)


def test_default_timeout_is_three_seconds():
    client = LiteLLMClient(base_url="http://litellm:4000")
    assert client._timeout_seconds == 3.0
