import numpy as np

from segment_capture.boundary import MessageStart
from segment_capture.recorder import SegmentRecorder


class _FakeRingReader:
    def __init__(self, preroll, new_chunks):
        self._preroll = preroll
        self._new_chunks = list(new_chunks)
        self.started = False

    def start(self, preroll_samples):
        self.started = True
        return self._preroll

    def read_new(self):
        if self._new_chunks:
            return self._new_chunks.pop(0), False
        return np.zeros(0, dtype=np.float32), False


class _FakeOverrunRingReader(_FakeRingReader):
    def __init__(self, preroll):
        super().__init__(preroll, [])
        self._overrun_next = True

    def read_new(self):
        if self._overrun_next:
            self._overrun_next = False
            return np.array([1.0], dtype=np.float32), True
        return np.zeros(0, dtype=np.float32), False


def _message_start(event_code="TOR"):
    return MessageStart(raw="ZCZC-...", event_code=event_code, fips_codes=("017021",))


def test_finalize_concatenates_preroll_and_drained_audio(tmp_path):
    preroll = np.array([1.0, 2.0], dtype=np.float32)
    new_audio = [np.array([3.0, 4.0], dtype=np.float32)]
    reader = _FakeRingReader(preroll, new_audio)
    recorder = SegmentRecorder("home", "WX5", _message_start(), reader, tmp_path)

    recorder.poll()
    result = recorder.finalize(timed_out=False)

    assert result.site == "home"
    assert result.channel == "WX5"
    assert result.event_code == "TOR"
    assert result.fips_codes == ("017021",)
    assert result.timed_out is False
    assert result.had_gap is False
    assert result.wav_path.exists()


def test_finalize_marks_gap_on_overrun(tmp_path):
    reader = _FakeOverrunRingReader(np.zeros(5, dtype=np.float32))
    recorder = SegmentRecorder("home", "WX5", _message_start(), reader, tmp_path)
    recorder.poll()
    result = recorder.finalize(timed_out=False)
    assert result.had_gap is True


def test_timed_out_uses_injectable_clock(tmp_path):
    clock = {"t": 0.0}
    reader = _FakeRingReader(np.zeros(5, dtype=np.float32), [])
    recorder = SegmentRecorder(
        "home",
        "WX5",
        _message_start(),
        reader,
        tmp_path,
        hard_timeout_seconds=10.0,
        now_fn=lambda: clock["t"],
    )
    assert recorder.timed_out() is False
    clock["t"] = 11.0
    assert recorder.timed_out() is True


def test_finalize_reports_timed_out_flag(tmp_path):
    reader = _FakeRingReader(np.zeros(5, dtype=np.float32), [])
    recorder = SegmentRecorder("home", "WX5", _message_start(), reader, tmp_path)
    result = recorder.finalize(timed_out=True)
    assert result.timed_out is True


def test_wav_filename_includes_site_channel_and_event_code(tmp_path):
    reader = _FakeRingReader(np.zeros(5, dtype=np.float32), [])
    recorder = SegmentRecorder("home", "WX5", _message_start("SVR"), reader, tmp_path)
    result = recorder.finalize(timed_out=False)
    assert "home" in result.wav_path.name
    assert "WX5" in result.wav_path.name
    assert "SVR" in result.wav_path.name
