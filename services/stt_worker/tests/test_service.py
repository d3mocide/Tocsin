import struct
import time
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
            "tier": "A",
            "fips_codes": ["017021"],
            "raw_header": "ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-",
            "wav_path": str(wav_path),
            "voice_start_sample": 2,
        }
    )

    assert len(sink.transcripts) == 1
    result = sink.transcripts[0]
    assert result.site == "home"
    assert result.channel == "WX5"
    assert result.event_code == "TOR"
    assert result.tier == "A"
    assert result.fips_codes == ("017021",)
    assert result.raw_header == "ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-"
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
            "tier": "A",
            "fips_codes": ["017021"],
            "raw_header": "ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-",
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
            "tier": "A",
            "fips_codes": [],
            "raw_header": "ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-",
            "wav_path": str(wav_path),
            "voice_start_sample": 2,
        }
    )

    assert seen_paths[0] != wav_path  # transcribed the *trimmed* copy, not the original
    assert sink.transcripts[0].text == "(3, 4, 5)"


def _payload(wav_path: Path, tier: str = "A") -> dict:
    return {
        "site": "home",
        "channel": "WX5",
        "event_code": "TOR",
        "tier": tier,
        "fips_codes": ["017021"],
        "raw_header": "ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-",
        "wav_path": str(wav_path),
        "voice_start_sample": None,
    }


def _slow_local(delay: float, transcript: Transcript):
    def run(wav_path, model_path, binary, language, initial_prompt):
        time.sleep(delay)
        return transcript

    return run


def _slow_remote(delay: float, transcript: Transcript = None, raises: Exception = None):
    def run(wav_path):
        time.sleep(delay)
        if raises:
            raise raises
        return transcript

    return run


def test_tier_b_never_races_remote(tmp_path):
    wav_path = tmp_path / "clip.wav"
    _write_wav(wav_path, [1, 2, 3])
    sink = FakeSink()
    remote_calls = []

    def remote_run(wav_path):
        remote_calls.append(wav_path)
        return Transcript(text="should not be used", segments=())

    worker = TranscriptionWorker(
        model_path="/models/m.bin",
        work_dir=tmp_path / "work",
        sink=sink,
        whisper_run=_fake_whisper_run(Transcript(text="local text", segments=())),
        remote_run=remote_run,
    )
    worker.handle_capture(_payload(wav_path, tier="B"))

    assert remote_calls == []
    assert sink.transcripts[0].text == "local text"


def test_no_remote_configured_uses_local_even_on_tier_a(tmp_path):
    wav_path = tmp_path / "clip.wav"
    _write_wav(wav_path, [1, 2, 3])
    sink = FakeSink()
    worker = TranscriptionWorker(
        model_path="/models/m.bin",
        work_dir=tmp_path / "work",
        sink=sink,
        whisper_run=_fake_whisper_run(Transcript(text="local text", segments=())),
        remote_run=None,
    )
    worker.handle_capture(_payload(wav_path, tier="A"))
    assert sink.transcripts[0].text == "local text"


def test_remote_wins_when_it_returns_in_budget_with_text(tmp_path):
    wav_path = tmp_path / "clip.wav"
    _write_wav(wav_path, [1, 2, 3])
    sink = FakeSink()
    worker = TranscriptionWorker(
        model_path="/models/m.bin",
        work_dir=tmp_path / "work",
        sink=sink,
        whisper_run=_slow_local(0.05, Transcript(text="local text", segments=())),
        remote_run=_slow_remote(0.05, Transcript(text="remote text", segments=())),
        remote_budget_seconds=1.0,
    )
    worker.handle_capture(_payload(wav_path, tier="A"))
    assert sink.transcripts[0].text == "remote text"


def test_local_wins_when_remote_exceeds_budget(tmp_path):
    wav_path = tmp_path / "clip.wav"
    _write_wav(wav_path, [1, 2, 3])
    sink = FakeSink()
    worker = TranscriptionWorker(
        model_path="/models/m.bin",
        work_dir=tmp_path / "work",
        sink=sink,
        whisper_run=_slow_local(0.02, Transcript(text="local text", segments=())),
        remote_run=_slow_remote(1.0, Transcript(text="remote text", segments=())),
        remote_budget_seconds=0.1,
    )
    start = time.monotonic()
    worker.handle_capture(_payload(wav_path, tier="A"))
    elapsed = time.monotonic() - start

    assert sink.transcripts[0].text == "local text"
    assert elapsed < 0.5  # didn't block waiting for the slow remote thread to actually finish


def test_local_wins_when_remote_raises(tmp_path):
    wav_path = tmp_path / "clip.wav"
    _write_wav(wav_path, [1, 2, 3])
    sink = FakeSink()
    worker = TranscriptionWorker(
        model_path="/models/m.bin",
        work_dir=tmp_path / "work",
        sink=sink,
        whisper_run=_slow_local(0.02, Transcript(text="local text", segments=())),
        remote_run=_slow_remote(0.0, raises=RuntimeError("connection refused")),
        remote_budget_seconds=1.0,
    )
    worker.handle_capture(_payload(wav_path, tier="A"))
    assert sink.transcripts[0].text == "local text"


def test_local_wins_when_remote_returns_empty_text(tmp_path):
    wav_path = tmp_path / "clip.wav"
    _write_wav(wav_path, [1, 2, 3])
    sink = FakeSink()
    worker = TranscriptionWorker(
        model_path="/models/m.bin",
        work_dir=tmp_path / "work",
        sink=sink,
        whisper_run=_slow_local(0.02, Transcript(text="local text", segments=())),
        remote_run=_slow_remote(0.02, Transcript(text="", segments=())),
        remote_budget_seconds=1.0,
    )
    worker.handle_capture(_payload(wav_path, tier="A"))
    assert sink.transcripts[0].text == "local text"


def _local_that_must_not_run(wav_path, model_path, binary, language, initial_prompt):
    raise AssertionError("local transcription ran with STT_CHAIN=remote")


def test_remote_only_transcribes_without_a_local_model(tmp_path):
    """`STT_CHAIN=remote`: no ggml model is staged, so `model_path` is
    `None` and whisper.cpp is never invoked."""
    wav_path = tmp_path / "clip.wav"
    _write_wav(wav_path, [1, 2, 3])
    sink = FakeSink()
    worker = TranscriptionWorker(
        model_path=None,
        work_dir=tmp_path / "work",
        sink=sink,
        whisper_run=_local_that_must_not_run,
        local_enabled=False,
        remote_run=lambda path: Transcript(text="remote text", segments=()),
    )
    worker.handle_capture(_payload(wav_path, tier="A"))
    assert sink.transcripts[0].text == "remote text"


def test_remote_only_covers_tier_b_too(tmp_path):
    """Tier B is local-only when a local provider exists to be preferred;
    with none, holding Tier B back would just drop those transcripts."""
    wav_path = tmp_path / "clip.wav"
    _write_wav(wav_path, [1, 2, 3])
    sink = FakeSink()
    worker = TranscriptionWorker(
        model_path=None,
        work_dir=tmp_path / "work",
        sink=sink,
        whisper_run=_local_that_must_not_run,
        local_enabled=False,
        remote_run=lambda path: Transcript(text="remote text", segments=()),
    )
    worker.handle_capture(_payload(wav_path, tier="B"))
    assert sink.transcripts[0].text == "remote text"
