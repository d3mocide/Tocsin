import struct
import wave
from pathlib import Path

from stt_worker.trim import trim_wav


def _write_wav(path: Path, samples: list[int], framerate: int = 16000) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(framerate)
        wav_file.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _read_wav_samples(path: Path) -> list[int]:
    with wave.open(str(path), "rb") as wav_file:
        raw = wav_file.readframes(wav_file.getnframes())
    return list(struct.unpack(f"<{len(raw) // 2}h", raw))


def test_trim_cuts_at_voice_start_sample(tmp_path):
    source = tmp_path / "source.wav"
    _write_wav(source, [1, 2, 3, 4, 5])
    dest = tmp_path / "trimmed.wav"

    trim_wav(source, dest, voice_start_sample=2)

    assert _read_wav_samples(dest) == [3, 4, 5]


def test_trim_with_none_copies_whole_file(tmp_path):
    source = tmp_path / "source.wav"
    _write_wav(source, [1, 2, 3])
    dest = tmp_path / "trimmed.wav"

    trim_wav(source, dest, voice_start_sample=None)

    assert _read_wav_samples(dest) == [1, 2, 3]


def test_trim_clamps_voice_start_past_end_of_file(tmp_path):
    source = tmp_path / "source.wav"
    _write_wav(source, [1, 2, 3])
    dest = tmp_path / "trimmed.wav"

    trim_wav(source, dest, voice_start_sample=1000)

    assert _read_wav_samples(dest) == []


def test_trim_preserves_wav_format_params(tmp_path):
    source = tmp_path / "source.wav"
    _write_wav(source, [1, 2, 3], framerate=16000)
    dest = tmp_path / "trimmed.wav"

    trim_wav(source, dest, voice_start_sample=0)

    with wave.open(str(dest), "rb") as wav_file:
        assert wav_file.getframerate() == 16000
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2


def test_trim_creates_parent_directories(tmp_path):
    source = tmp_path / "source.wav"
    _write_wav(source, [1, 2, 3])
    dest = tmp_path / "nested" / "dir" / "trimmed.wav"

    trim_wav(source, dest, voice_start_sample=0)

    assert dest.exists()
