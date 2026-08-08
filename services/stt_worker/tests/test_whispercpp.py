import json
import sys
from pathlib import Path

from stt_worker.whispercpp import build_command, parse_transcript, run


def test_parse_transcript_concatenates_segment_text():
    data = {"transcription": [{"text": "hello "}, {"text": "world"}]}
    transcript = parse_transcript(data)
    assert transcript.text == "hello world"


def test_parse_transcript_extracts_confidence_fields():
    data = {"transcription": [{"text": "hi", "no_speech_prob": 0.3, "avg_logprob": -0.5}]}
    transcript = parse_transcript(data)
    assert transcript.segments[0].no_speech_prob == 0.3
    assert transcript.segments[0].avg_logprob == -0.5


def test_parse_transcript_handles_missing_confidence_fields():
    """Not every whisper.cpp build supplies these -- see the module
    docstring. Their absence must not raise or be treated as 0.0."""
    data = {"transcription": [{"text": "hi"}]}
    transcript = parse_transcript(data)
    assert transcript.segments[0].no_speech_prob is None
    assert transcript.segments[0].avg_logprob is None


def test_parse_transcript_handles_no_segments():
    transcript = parse_transcript({"transcription": []})
    assert transcript.text == ""
    assert transcript.segments == ()


def test_run_invokes_command_factory_and_parses_result(tmp_path):
    wav_path = tmp_path / "clip.wav"
    captured_args = {}

    def fake_factory(binary, model_path, wpath, output_prefix, language, initial_prompt):
        captured_args.update(
            binary=binary, model_path=model_path, wav_path=wpath, language=language, initial_prompt=initial_prompt
        )
        output_prefix.with_suffix(".json").write_text(json.dumps({"transcription": [{"text": "tornado warning"}]}))
        return [sys.executable, "-c", "pass"]

    transcript = run(
        wav_path,
        "/models/ggml-base.en.bin",
        binary="whisper-cli",
        language="en",
        initial_prompt="Portland",
        command_factory=fake_factory,
    )

    assert transcript.text == "tornado warning"
    assert captured_args["model_path"] == "/models/ggml-base.en.bin"
    assert captured_args["wav_path"] == wav_path
    assert captured_args["initial_prompt"] == "Portland"


def test_build_command_shape():
    cmd = build_command("whisper-cli", "/models/m.bin", Path("/tmp/in.wav"), Path("/tmp/out"), "en", None)
    assert cmd[0] == "whisper-cli"
    assert cmd[cmd.index("-m") + 1] == "/models/m.bin"
    assert cmd[cmd.index("-f") + 1] == "/tmp/in.wav"
    assert cmd[cmd.index("-of") + 1] == "/tmp/out"
    assert "-oj" in cmd and "-ojf" in cmd
    assert "--prompt" not in cmd


def test_build_command_includes_prompt_when_given():
    cmd = build_command("whisper-cli", "/models/m.bin", Path("/tmp/in.wav"), Path("/tmp/out"), "en", "Portland Multnomah")
    assert cmd[cmd.index("--prompt") + 1] == "Portland Multnomah"
