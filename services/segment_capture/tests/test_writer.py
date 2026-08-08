import wave

import numpy as np

from segment_capture.ring_reader import RING_BUFFER_SAMPLE_RATE_HZ
from segment_capture.writer import STT_RATE_HZ, ring_rate_sample_to_stt_rate, write_wav


def test_write_wav_produces_correct_format(tmp_path):
    t = np.arange(RING_BUFFER_SAMPLE_RATE_HZ) / RING_BUFFER_SAMPLE_RATE_HZ
    samples = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    path = tmp_path / "out.wav"
    num_samples = write_wav(path, samples)

    with wave.open(str(path), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == STT_RATE_HZ
        assert wav_file.getnframes() == num_samples

    # 1 second of ring-rate audio -> 1 second of STT-rate audio
    assert num_samples == STT_RATE_HZ


def test_write_wav_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "out.wav"
    write_wav(path, np.zeros(100, dtype=np.float32))
    assert path.exists()


def test_ring_rate_sample_to_stt_rate_scales_correctly():
    assert ring_rate_sample_to_stt_rate(RING_BUFFER_SAMPLE_RATE_HZ) == STT_RATE_HZ
    assert ring_rate_sample_to_stt_rate(0) == 0
