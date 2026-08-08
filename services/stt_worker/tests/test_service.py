import struct
import wave
from pathlib import Path

from stt_worker.service import TranscriptionWorker
from stt_worker.whispercpp import Segment, Transcript


class FakeSink:
    def __init__(self):
        self.transcripts = []

    def record(self, transcript):
        self.transcripts.append(transcript)


def _write_wav(path: Path, samples: list[int]) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _fake_whisper_run(transcript: Transcript):
    def run(wav_path, model_path, binary, language, initial_prompt):
        return transcript

    return run


def test_handle_capture_records_a_passing_transcript(tmp_path):
    wav_path = tmp_path / "clip.wav"
    _write_wav(wav_path, [1, 2, 3, 4, 5])
    sink = FakeSink()
    transcript = Transcript(text="a tornado warning", segments=(Segment("a tornado warning", 0.05, -0.2),))
    worker = TranscriptionWorker(
        model_path="/models/m.bin",
        work_dir=tmp_path / "work",
        sink=sink,
        whisper_run=_fake_whisper_run(transcript),
    )

    worker.handle_capture(
        {
            "site": "home",
            "channel": "WX5",
            "event_code": "TOR",
            "fips_codes": ["017021"],
            "wav_path": str(wav_path),
            "voice_start_sample": 2,
        }
    )

    assert len(sink.transcripts) == 1
    result = sink.transcripts[0]
    assert result.site == "home"
    assert result.channel == "WX5"
    assert result.event_code == "TOR"
    assert result.fips_codes == ("017021",)
    assert result.text == "a tornado warning"
    assert result.passed_guard is True
    assert result.guard_reason is None


def test_handle_capture_blanks_text_when_guard_fails(tmp_path):
    wav_path = tmp_path / "clip.wav"
    _write_wav(wav_path, [1, 2, 3])
    sink = FakeSink()
    transcript = Transcript(text="Thank you for watching!", segments=(Segment("Thank you for watching!", 0.01, -0.1),))
    worker = TranscriptionWorker(
        model_path="/models/m.bin",
        work_dir=tmp_path / "work",
        sink=sink,
        whisper_run=_fake_whisper_run(transcript),
    )

    worker.handle_capture(
        {
            "site": "home",
            "channel": "WX5",
            "event_code": "TOR",
            "fips_codes": ["017021"],
            "wav_path": str(wav_path),
            "voice_start_sample": None,
        }
    )

    result = sink.transcripts[0]
    assert result.passed_guard is False
    assert result.text == ""
    assert "blocklist" in result.guard_reason


def test_handle_capture_trims_wav_before_transcribing(tmp_path):
    wav_path = tmp_path / "clip.wav"
    _write_wav(wav_path, [1, 2, 3, 4, 5])
    sink = FakeSink()
    seen_paths = []

    def whisper_run(wav_path_arg, model_path, binary, language, initial_prompt):
        seen_paths.append(wav_path_arg)
        with wave.open(str(wav_path_arg), "rb") as wav_file:
            raw = wav_file.readframes(wav_file.getnframes())
        samples = struct.unpack(f"<{len(raw) // 2}h", raw)
        return Transcript(text=str(samples), segments=())

    worker = TranscriptionWorker(
        model_path="/models/m.bin", work_dir=tmp_path / "work", sink=sink, whisper_run=whisper_run
    )
    worker.handle_capture(
        {
            "site": "home",
            "channel": "WX5",
            "event_code": "TOR",
            "fips_codes": [],
            "wav_path": str(wav_path),
            "voice_start_sample": 2,
        }
    )

    assert seen_paths[0] != wav_path  # transcribed the *trimmed* copy, not the original
    assert sink.transcripts[0].text == "(3, 4, 5)"
