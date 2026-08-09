"""CLI diagnostic tool to test remote Whisper HTTP transcription endpoints
(STT_WORKER_REMOTE_BASE_URL) directly.

Usage:
    uv run python -m stt_worker.test_remote [path/to/audio.wav]
"""

from __future__ import annotations

import os
import sys
import tempfile
import wave
from pathlib import Path

from . import remote_http


def _generate_dummy_wav(path: Path) -> None:
    """Generates a 1-second silent WAV file for testing connectivity when no audio file is provided."""
    sample_rate = 22050
    num_samples = sample_rate
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        raw_data = b"\x00\x00" * num_samples
        wav_file.writeframes(raw_data)


def main() -> None:
    base_url = os.environ.get("STT_WORKER_REMOTE_BASE_URL")
    if not base_url:
        print(
            "ERROR: STT_WORKER_REMOTE_BASE_URL is not set in environment.\n"
            "Example: export STT_WORKER_REMOTE_BASE_URL=http://localhost:8000\n"
            "Set this variable in your .env or environment to test your remote Whisper endpoint.",
            file=sys.stderr,
        )
        sys.exit(1)

    api_key = os.environ.get("STT_WORKER_REMOTE_API_KEY") or None
    model = os.environ.get("STT_WORKER_REMOTE_MODEL", remote_http.DEFAULT_MODEL)

    wav_path: Path | None = None
    temp_dir = None

    if len(sys.argv) > 1:
        provided_path = Path(sys.argv[1])
        if not provided_path.is_file():
            print(f"ERROR: Audio file {provided_path} does not exist.", file=sys.stderr)
            sys.exit(1)
        wav_path = provided_path
    else:
        temp_dir = tempfile.TemporaryDirectory()
        wav_path = Path(temp_dir.name) / "test_sample.wav"
        _generate_dummy_wav(wav_path)
        print(f"No WAV file specified; using generated 1s test WAV at {wav_path}")

    print(f"Testing Remote Whisper Endpoint:")
    print(f"  URL:   {base_url.rstrip('/')}/v1/audio/transcriptions")
    print(f"  Model: {model}")
    print(f"  Key:   {'[set]' if api_key else '[unset]'}")
    print(f"  WAV:   {wav_path}")
    print("Sending request...")

    try:
        result = remote_http.run(
            wav_path=wav_path,
            base_url=base_url,
            api_key=api_key,
            model=model,
        )
        print("\n--- Remote Whisper Response SUCCESS ---")
        print(f"Transcribed Text: {result.text!r}")
        print("--------------------------------------")
    except Exception as exc:
        print(f"\n--- Remote Whisper Request FAILED ---", file=sys.stderr)
        print(f"Error: {exc}", file=sys.stderr)
        print("Check your base URL, API key, model name, and backend logs.", file=sys.stderr)
        sys.exit(1)
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


if __name__ == "__main__":
    main()
