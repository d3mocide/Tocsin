"""HTTP client for LiteLLM's OpenAI-compatible `/chat/completions`
endpoint (design doc §7's stage-2 enrichment). Verified against LiteLLM's
own docs this session, not guessed: standard OpenAI chat-completions
request/response shape (`{"model", "messages"}` -> `choices[0].message.
content`), `Authorization: Bearer <key>` auth, `/chat/completions` (also
accepts `/v1/chat/completions`).

Hard 3s timeout (design doc §7: "3s LiteLLM timeout... or this will
eventually hang the dispatcher") -- deliberately short: stage 1 already
delivered by the time stage 2 runs (T+60-120s per the design doc), so
there's no reason to let a slow LLM endpoint hold up the next alert in the
stream.
"""

from __future__ import annotations

from typing import Callable, Protocol

import requests

DEFAULT_TIMEOUT_SECONDS = 3.0
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_MAX_TOKENS = 120

_SYSTEM_PROMPT = (
    "You compress NOAA weather warning transcripts into a single short "
    "impact clause for a low-bandwidth mesh radio broadcast. Respond with "
    "ONLY the impact clause -- no preamble, no quotes, no newlines, ASCII "
    "only, under {max_bytes} bytes."
)


class HttpResponse(Protocol):
    status_code: int

    def json(self) -> dict: ...
    def raise_for_status(self) -> None: ...


PostFn = Callable[..., HttpResponse]


class LiteLLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        post: PostFn = requests.post,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._post = post

    def compress(self, transcript_text: str, max_bytes: int) -> str:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT.format(max_bytes=max_bytes)},
                {"role": "user", "content": transcript_text},
            ],
            "max_tokens": DEFAULT_MAX_TOKENS,
        }
        response = self._post(
            f"{self._base_url}/chat/completions",
            json=body,
            headers=headers,
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
