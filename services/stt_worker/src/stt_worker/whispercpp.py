"""Subprocess wrapper around whisper.cpp's `whisper-cli` binary (design
doc §6's `local_whispercpp` provider -- the only provider implemented so
far; CLAUDE.md says to stay concrete here until a second real provider
exists to generalize from, not build a pluggable interface up front).

Requests whisper.cpp's "full" JSON output (`-oj -ojf`) so hallucination
guard fields land in the same call as the transcript. Two caveats found
via research (ggml-org/whisper.cpp's CLI README and source) rather than
assumed, since an unguarded transcript is this system's worst failure
chain per the design doc:

- `no_speech_prob` per segment was only added to whisper.cpp's JSON writer
  in a 2026 PR (ggml-org/whisper.cpp#2654) -- present on a recent enough
  build (see the Dockerfile's pinned version), possibly absent otherwise.
- `avg_logprob`, the design doc's other named metric, does not appear to
  be exposed through whisper.cpp's CLI JSON output at all as of this
  writing -- it exists internally in the decoder's fallback logic but
  isn't wired into the JSON writer, and no documented flag requests it.

Rather than hard-require either field and have the guard break (or
silently no-op) depending on the exact whisper.cpp build in the image,
`guard.py` checks each threshold only when the corresponding field is
actually present in a given segment's JSON -- see its docstring. The
blocklist check there is unconditional and doesn't depend on any of this.

Unlike `same_decoder`/`segment_capture`'s multimon-ng wrappers (a single
injectable stdin/stdout command), whisper-cli's real interface is
file-based (`-f <input wav>`, `-of <output prefix>` writing
`<prefix>.json`), so the injection seam here is a `command_factory`
function rather than a literal command list -- a test's fake factory can
write the fixture JSON directly at the expected path as a side effect,
without needing a subprocess that understands whisper-cli's argv contract.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from .transcript import Segment, Transcript  # re-exported -- see transcript.py's docstring

DEFAULT_BINARY = "whisper-cli"
DEFAULT_LANGUAGE = "en"

__all__ = ["Segment", "Transcript", "build_command", "parse_transcript", "run", "DEFAULT_BINARY", "DEFAULT_LANGUAGE"]


def build_command(
    binary: str,
    model_path: str,
    wav_path: Path,
    output_prefix: Path,
    language: str,
    initial_prompt: str | None,
) -> list[str]:
    command = [
        binary,
        "-m", model_path,
        "-f", str(wav_path),
        "-oj", "-ojf",
        "-of", str(output_prefix),
        "-l", language,
    ]  # fmt: skip
    if initial_prompt:
        command += ["--prompt", initial_prompt]
    return command


CommandFactory = Callable[[str, str, Path, Path, str, "str | None"], list[str]]


def parse_transcript(data: dict) -> Transcript:
    segments = tuple(
        Segment(
            text=entry.get("text", ""),
            no_speech_prob=entry.get("no_speech_prob"),
            avg_logprob=entry.get("avg_logprob"),
        )
        for entry in data.get("transcription", [])
    )
    full_text = "".join(segment.text for segment in segments).strip()
    return Transcript(text=full_text, segments=segments)


def run(
    wav_path: Path,
    model_path: str,
    binary: str = DEFAULT_BINARY,
    language: str = DEFAULT_LANGUAGE,
    initial_prompt: str | None = None,
    command_factory: CommandFactory = build_command,
) -> Transcript:
    """Runs whisper-cli against `wav_path` and parses its JSON output.
    Raises `subprocess.CalledProcessError` if whisper-cli itself fails."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        output_prefix = Path(tmp_dir) / wav_path.stem
        command = command_factory(binary, model_path, wav_path, output_prefix, language, initial_prompt)
        subprocess.run(command, check=True, capture_output=True)
        data = json.loads(output_prefix.with_suffix(".json").read_text())
    return parse_transcript(data)
