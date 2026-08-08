import json

import zmq

from stt_worker.subscriber import CaptureSubscriber


def _publish_with_retry(pub: zmq.Socket, sub: CaptureSubscriber, frames, attempts: int = 25):
    for _ in range(attempts):
        pub.send_multipart(frames)
        received = sub.recv(timeout_ms=200)
        if received is not None:
            return received
    raise AssertionError("subscriber never received the message")


def test_recv_decodes_json_payload():
    ctx = zmq.Context()
    pub = ctx.socket(zmq.PUB)
    pub.bind("inproc://stt-sub-1")
    sub = CaptureSubscriber("inproc://stt-sub-1", context=ctx)

    payload = {"site": "home", "channel": "WX5", "wav_path": "/tmp/x.wav", "voice_start_sample": 100}
    frames = [b"capture.home.WX5", json.dumps(payload).encode()]
    result = _publish_with_retry(pub, sub, frames)

    assert result == payload

    sub.close()
    pub.close(linger=0)
    ctx.term()


def test_recv_times_out_when_nothing_arrives():
    ctx = zmq.Context()
    sub = CaptureSubscriber("inproc://stt-sub-2", context=ctx)
    assert sub.recv(timeout_ms=50) is None
    sub.close()
    ctx.term()


def test_subscriber_ignores_non_capture_topics():
    ctx = zmq.Context()
    pub = ctx.socket(zmq.PUB)
    pub.bind("inproc://stt-sub-3")
    sub = CaptureSubscriber("inproc://stt-sub-3", context=ctx)

    frames = [b"same.home.WX5", json.dumps({"unrelated": True}).encode()]
    for _ in range(10):
        pub.send_multipart(frames)
    assert sub.recv(timeout_ms=200) is None

    sub.close()
    pub.close(linger=0)
    ctx.term()
