"""Resamples the ring buffer's raw discriminator output to the 16 kHz mono
s16le WAV format `stt_worker`'s uniform provider contract requires (design
doc §6), and writes it to disk.

Duplicates `sdr_rx.resample`'s STT-rate conversion (8/25 `resample_poly` +
clip-and-scale to int16) rather than importing across the service boundary
(CLAUDE.md) -- writing an already-contract-compliant WAV here means
`stt_worker` needs no format-conversion code of its own, only trimming and
inference.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from .ring_reader import RING_BUFFER_SAMPLE_RATE_HZ

STT_RATE_HZ = 16_000


def to_stt_rate(audio: np.ndarray) -> np.ndarray:
    return resample_poly(audio, 8, 25)


def to_s16le(audio: np.ndarray) -> np.ndarray:
    return (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)


def ring_rate_sample_to_stt_rate(sample_index_at_ring_rate: int) -> int:
    return int(sample_index_at_ring_rate * STT_RATE_HZ / RING_BUFFER_SAMPLE_RATE_HZ)


def write_wav(path: Path, samples_at_ring_rate: np.ndarray) -> int:
    """Resamples `samples_at_ring_rate` (raw discriminator output at
    `RING_BUFFER_SAMPLE_RATE_HZ`) to 16 kHz s16le mono and writes a WAV
    file at `path`. Returns the number of STT-rate samples written."""
    stt_audio = to_s16le(to_stt_rate(samples_at_ring_rate))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(STT_RATE_HZ)
        wav_file.writeframes(stt_audio.tobytes())
    return len(stt_audio)
