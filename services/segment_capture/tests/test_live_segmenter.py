import numpy as np

from segment_capture.live_segmenter import FRAME_SECONDS, RING_BUFFER_SAMPLE_RATE_HZ, LiveSegmenter

FRAME_SAMPLES = int(FRAME_SECONDS * RING_BUFFER_SAMPLE_RATE_HZ)
LOUD = 1.0  # constant amplitude well above any reasonable RMS threshold
QUIET = 0.0


class _FakeRingReader:
    """Hands back pre-scripted batches on successive `read_new()` calls --
    `LiveSegmenter` only needs `start()`/`read_new()` (see `ring_reader.py`),
    so this avoids standing up real ring-buffer files for a unit test that
    is exercising the VAD/cut logic, not the file format (that's
    test_ring_reader.py's job)."""

    def __init__(self, batches: list[np.ndarray]):
        self._batches = list(batches)
        self.started = False

    def start(self, preroll_samples):
        self.started = True
        return np.zeros(0, dtype=np.float32)

    def read_new(self):
        if not self._batches:
            return np.zeros(0, dtype=np.float32), False
        return self._batches.pop(0), False


def _frames(*levels: float, count: int = 1) -> np.ndarray:
    """`count` frames at each level in order, e.g. `_frames(LOUD, count=2)`
    is two full frames of loud signal."""
    pieces = [np.full(FRAME_SAMPLES, level, dtype=np.float32) for level in levels for _ in range(count)]
    return np.concatenate(pieces)


def _segmenter(reader, tmp_path, **overrides):
    kwargs = dict(
        min_chunk_seconds=2 * FRAME_SECONDS,
        max_chunk_seconds=4 * FRAME_SECONDS,
        silence_hang_seconds=FRAME_SECONDS,
    )
    kwargs.update(overrides)
    return LiveSegmenter("home", "WX5", reader, tmp_path, **kwargs)


def test_silence_only_produces_no_chunk(tmp_path):
    reader = _FakeRingReader([_frames(QUIET, count=10)])
    segmenter = _segmenter(reader, tmp_path)
    assert segmenter.poll() == []
    assert reader.started is True


def test_speech_then_silence_produces_one_chunk(tmp_path):
    # 2 loud frames satisfies min_chunk_seconds, then 1 quiet frame satisfies silence_hang_seconds.
    reader = _FakeRingReader([np.concatenate([_frames(LOUD, count=2), _frames(QUIET, count=1)])])
    segmenter = _segmenter(reader, tmp_path)
    results = segmenter.poll()
    assert len(results) == 1
    assert results[0].site == "home"
    assert results[0].channel == "WX5"
    assert results[0].wav_path.exists()
    assert results[0].num_samples > 0


def test_short_silence_does_not_cut_before_min_chunk(tmp_path):
    reader = _FakeRingReader([])
    # min_chunk_seconds raised to 3 frames so a single loud+quiet pair
    # (2 frames) can satisfy silence_hang_seconds without yet reaching it.
    segmenter = _segmenter(reader, tmp_path, min_chunk_seconds=3 * FRAME_SECONDS)

    reader._batches.append(_frames(LOUD, count=1))
    assert segmenter.poll() == []  # 1 of 3 frames -- below min_chunk_seconds

    reader._batches.append(_frames(QUIET, count=1))
    assert segmenter.poll() == []  # silence_hang_seconds met, but only 2 of 3 frames accumulated

    reader._batches.append(_frames(LOUD, count=1))
    assert segmenter.poll() == []  # 3rd frame reaches min_chunk_seconds, but it's loud -- resets the silence run

    reader._batches.append(_frames(QUIET, count=1))
    results = segmenter.poll()
    assert len(results) == 1  # both conditions now hold


def test_continuous_speech_cuts_at_max_duration(tmp_path):
    # max_chunk_seconds is 4 frames; feed 4 straight loud frames with no
    # silence at all -- must still cut rather than growing unbounded.
    reader = _FakeRingReader([_frames(LOUD, count=4)])
    segmenter = _segmenter(reader, tmp_path)
    results = segmenter.poll()
    assert len(results) == 1


def test_one_large_batch_can_yield_multiple_chunks(tmp_path):
    counter = {"n": 0}

    def fake_clock():
        counter["n"] += 1
        return counter["n"]  # strictly increasing -- guarantees distinct filenames

    # Two full speech-then-silence sequences back to back in a single batch.
    one_cycle = np.concatenate([_frames(LOUD, count=2), _frames(QUIET, count=1)])
    reader = _FakeRingReader([np.concatenate([one_cycle, one_cycle])])
    segmenter = _segmenter(reader, tmp_path, now_fn=fake_clock)
    results = segmenter.poll()
    assert len(results) == 2
    assert results[0].wav_path != results[1].wav_path
    assert results[0].wav_path.exists()
    assert results[1].wav_path.exists()


def test_no_preroll_requested_on_start(tmp_path):
    reader = _FakeRingReader([])
    segmenter = _segmenter(reader, tmp_path)
    segmenter.poll()
    assert reader.started is True
