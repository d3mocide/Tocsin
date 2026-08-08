import json

import zmq

from live_audio.subscriber import StreamAudioSubscriber


def _publish_with_retry(pub: zmq.Socket, sub: StreamAudioSubscriber, frames, attempts: int = 25):
    for _ in range(attempts):
        pub.send_multipart(frames)
        received = sub.recv(timeout_ms=200)
        if received is not None:
            return received
    raise AssertionError("subscriber never received the message")


def test_recv_decodes_site_channel_rate_and_pcm():
    ctx = zmq.Context()
    pub = ctx.socket(zmq.PUB)
    pub.bind("inproc://live-audio-sub-1")
    sub = StreamAudioSubscriber("inproc://live-audio-sub-1", context=ctx)

    header = {"site": "home", "channel": "WX5", "sample_rate_hz": 16000, "num_samples": 4}
    frames = [b"stt.home.WX5", json.dumps(header).encode(), b"\x01\x02\x03\x04"]
    result = _publish_with_retry(pub, sub, frames)

    assert result == ("home", "WX5", 16000, b"\x01\x02\x03\x04")

    sub.close()
    pub.close(linger=0)
    ctx.term()


def test_subscriber_ignores_non_stt_topics():
    ctx = zmq.Context()
    pub = ctx.socket(zmq.PUB)
    pub.bind("inproc://live-audio-sub-2")
    sub = StreamAudioSubscriber("inproc://live-audio-sub-2", context=ctx)

    header = {"site": "home", "channel": "WX5", "sample_rate_hz": 22050, "num_samples": 1}
    same_frames = [b"same.home.WX5", json.dumps(header).encode(), b"\x00"]

    for _ in range(10):
        pub.send_multipart(same_frames)
    assert sub.recv(timeout_ms=200) is None

    sub.close()
    pub.close(linger=0)
    ctx.term()


def test_recv_times_out_when_nothing_arrives():
    ctx = zmq.Context()
    sub = StreamAudioSubscriber("inproc://live-audio-sub-3", context=ctx)
    assert sub.recv(timeout_ms=50) is None
    sub.close()
    ctx.term()
