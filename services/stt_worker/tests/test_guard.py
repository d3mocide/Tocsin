from stt_worker.guard import check_transcript
from stt_worker.whispercpp import Segment, Transcript


def test_clean_transcript_passes():
    transcript = Transcript(
        text="a tornado warning has been issued",
        segments=(Segment(text="a tornado warning has been issued", no_speech_prob=0.05, avg_logprob=-0.2),),
    )
    result = check_transcript(transcript)
    assert result.passed is True
    assert result.reason is None


def test_high_no_speech_prob_fails():
    transcript = Transcript(
        text="some confident garbage",
        segments=(Segment(text="some confident garbage", no_speech_prob=0.95, avg_logprob=-0.2),),
    )
    result = check_transcript(transcript)
    assert result.passed is False
    assert "no_speech_prob" in result.reason


def test_low_avg_logprob_fails():
    transcript = Transcript(
        text="some confident garbage",
        segments=(Segment(text="some confident garbage", no_speech_prob=0.05, avg_logprob=-2.5),),
    )
    result = check_transcript(transcript)
    assert result.passed is False
    assert "avg_logprob" in result.reason


def test_missing_confidence_fields_do_not_fail_the_guard():
    """Not every whisper.cpp build supplies no_speech_prob/avg_logprob --
    see whispercpp.py's docstring. Their absence must not silently pass
    OR silently fail; it should simply not be checked, leaving the
    blocklist as the guarantee that still applies."""
    transcript = Transcript(
        text="a tornado warning has been issued",
        segments=(Segment(text="a tornado warning has been issued", no_speech_prob=None, avg_logprob=None),),
    )
    result = check_transcript(transcript)
    assert result.passed is True


def test_blocklist_catches_classic_hallucination():
    transcript = Transcript(
        text="Thank you for watching!",
        segments=(Segment(text="Thank you for watching!", no_speech_prob=0.01, avg_logprob=-0.1),),
    )
    result = check_transcript(transcript)
    assert result.passed is False
    assert "blocklist" in result.reason


def test_blocklist_is_case_insensitive():
    transcript = Transcript(
        text="PLEASE LIKE AND SUBSCRIBE",
        segments=(Segment(text="PLEASE LIKE AND SUBSCRIBE", no_speech_prob=0.01, avg_logprob=-0.1),),
    )
    result = check_transcript(transcript)
    assert result.passed is False


def test_custom_thresholds_are_respected():
    transcript = Transcript(
        text="borderline",
        segments=(Segment(text="borderline", no_speech_prob=0.5, avg_logprob=-0.2),),
    )
    assert check_transcript(transcript, no_speech_prob_threshold=0.6).passed is True
    assert check_transcript(transcript, no_speech_prob_threshold=0.4).passed is False
