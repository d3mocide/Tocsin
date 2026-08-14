import json
from pathlib import Path

import zmq

from segment_capture.bus import CapturePublisher
from segment_capture.live_segmenter import LiveCaptureResult
from segment_capture.recorder import CaptureResult


def _recv_with_retry(sub: zmq.Socket, send_fn, timeout_ms: int = 200, attempts: int = 25):
    for _ in range(attempts):
        send_fn()
        if sub.poll(timeout_ms):
            return sub.recv_multipart()
    raise AssertionError("no message received from publisher")


def _result(**overrides) -> CaptureResult:
    defaults = dict(
        site="home",
        channel="WX5",
        event_code="TOR",
        tier="A",
        fips_codes=("017021",),
        raw_header="ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-",
        wav_path=Path("/tmp/home-WX5-TOR-1.wav"),
        voice_start_sample=12345,
        num_samples=50000,
        timed_out=False,
        had_gap=False,
    )
    defaults.update(overrides)
    return CaptureResult(**defaults)


def test_publish_sends_topic_and_json_payload():
    ctx = zmq.Context()
    pub = CapturePublisher("inproc://test-capture-bus-1", context=ctx)
    sub = ctx.socket(zmq.SUB)
    sub.connect("inproc://test-capture-bus-1")
    sub.setsockopt(zmq.SUBSCRIBE, b"")

    frames = _recv_with_retry(sub, lambda: pub.publish(_result()))

    topic, payload_bytes = frames
    assert topic == b"capture.home.WX5"
    payload = json.loads(payload_bytes)
    assert payload["capture_kind"] == "alert"
    assert payload["site"] == "home"
    assert payload["channel"] == "WX5"
    assert payload["event_code"] == "TOR"
    assert payload["tier"] == "A"
    assert payload["fips_codes"] == ["017021"]
    assert payload["raw_header"] == "ZCZC-WXR-TOR-017021+0045-1000042-KILX/NWS-"
    assert payload["wav_path"] == "/tmp/home-WX5-TOR-1.wav"
    assert payload["voice_start_sample"] == 12345
    assert payload["num_samples"] == 50000
    assert payload["timed_out"] is False
    assert payload["had_gap"] is False

    pub.close()
    sub.close()
    ctx.term()


def test_voice_start_sample_can_be_null():
    ctx = zmq.Context()
    pub = CapturePublisher("inproc://test-capture-bus-2", context=ctx)
    sub = ctx.socket(zmq.SUB)
    sub.connect("inproc://test-capture-bus-2")
    sub.setsockopt(zmq.SUBSCRIBE, b"")

    frames = _recv_with_retry(sub, lambda: pub.publish(_result(voice_start_sample=None)))
    payload = json.loads(frames[1])
    assert payload["voice_start_sample"] is None

    pub.close()
    sub.close()
    ctx.term()


def test_publish_live_sends_topic_and_minimal_payload():
    ctx = zmq.Context()
    pub = CapturePublisher("inproc://test-capture-bus-3", context=ctx)
    sub = ctx.socket(zmq.SUB)
    sub.connect("inproc://test-capture-bus-3")
    sub.setsockopt(zmq.SUBSCRIBE, b"")

    result = LiveCaptureResult(site="home", channel="WX5", wav_path=Path("/tmp/home-WX5-live-1.wav"), num_samples=8000)
    frames = _recv_with_retry(sub, lambda: pub.publish_live(result))

    topic, payload_bytes = frames
    assert topic == b"capture.home.WX5"
    payload = json.loads(payload_bytes)
    assert payload["capture_kind"] == "live"
    assert payload["site"] == "home"
    assert payload["channel"] == "WX5"
    assert payload["wav_path"] == "/tmp/home-WX5-live-1.wav"
    assert payload["num_samples"] == 8000
    # No SAME-derived fields at all -- nothing has been decoded or matched
    # yet at capture time for a live chunk.
    assert "event_code" not in payload
    assert "tier" not in payload

    pub.close()
    sub.close()
    ctx.term()
