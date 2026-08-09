"""HTTP client for the `remote_http` STT provider (design doc §6): an
OpenAI-compatible `POST /v1/audio/transcriptions` endpoint. "That one
remote endpoint shape covers a self-hosted faster-whisper-server, LiteLLM
routing, or a commercial API with no code change between them" -- the
whole reason to target this shape instead of anything provider-specific.

Multipart form upload (`file`, `model`), default JSON response
`{"text": "..."}` -- the standard, stable OpenAI API shape. No
`no_speech_prob`/`avg_logprob`-equivalent fields are guaranteed here the
way local whisper.cpp's JSON output has (see `whispercpp.py`'s
docstring), so a remote transcript always comes back with empty
`segments` -- `guard.py` already handles that gracefully (it only checks
a threshold when the field is present on a segment), same posture as a
whisper.cpp build that doesn't expose those fields either.

The file part's Content-Type is derived via `mimetypes.guess_type`
(`.wav` -> `audio/x-wav`) rather than a literal `"audio/wav"`, to match
what `openai`/`httpx` (and therefore LiteLLM's SDK, and Vertex's own
whisper client -- a sibling project confirmed working against the same
self-hosted backend) actually send for the same file. Found the hard way:
a self-hosted whisper backend that keys its upload-format detection off
the declared Content-Type, doesn't recognize the literal string
`"audio/wav"`, and falls back to assuming mp3 -- which fails outright
(ffmpeg forced into the wrong demuxer) rather than degrading gracefully.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Callable, Protocol

import requests

from .transcript import Transcript

DEFAULT_TIMEOUT_SECONDS = 30.0  # a real transcription call, not the fast LiteLLM path -- generous on purpose
DEFAULT_MODEL = "whisper-1"


class HttpResponse(Protocol):
    status_code: int

    def json(self) -> dict: ...
    def raise_for_status(self) -> None: ...


PostFn = Callable[..., HttpResponse]


def run(
    wav_path: Path,
    base_url: str,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    post: PostFn = requests.post,
) -> Transcript:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    content_type = mimetypes.guess_type(wav_path.name)[0] or "application/octet-stream"
    with wav_path.open("rb") as f:
        response = post(
            f"{base_url.rstrip('/')}/v1/audio/transcriptions",
            headers=headers,
            files={"file": (wav_path.name, f, content_type)},
            data={"model": model},
            timeout=timeout_seconds,
        )
    response.raise_for_status()
    text = (response.json().get("text") or "").strip()
    return Transcript(text=text, segments=())
