import json

import zmq

from same_decoder.subscriber import SameAudioSubscriber


def _publish_with_retry(pub: zmq.Socket, sub: SameAudioSubscriber, frames, attempts: int = 25):
    """inproc PUB/SUB needs the SUB's subscription to propagate before a
    send is visible to it -- retry the send until recv() sees it, same
    approach as sdr_rx's bus tests."""
    for _ in range(attempts):
        pub.send_multipart(frames)
        received = sub.recv(timeout_ms=200)
        if received is not None:
            return received
    raise AssertionError("subscriber never received the message")


def test_recv_decodes_site_channel_rate_and_pcm():
    ctx = zmq.Context()
    pub = ctx.socket(zmq.PUB)
    pub.bind("inproc://same-sub-1")
    sub = SameAudioSubscriber("inproc://same-sub-1", context=ctx)

    header = {"site": "home", "channel": "WX5", "sample_rate_hz": 22050, "num_samples": 4}
    frames = [b"same.home.WX5", json.dumps(header).encode(), b"\x01\x02\x03\x04"]
    result = _publish_with_retry(pub, sub, frames)

    assert result == ("home", "WX5", 22050, b"\x01\x02\x03\x04")

    sub.close()
    pub.close(linger=0)
    ctx.term()


def test_recv_times_out_when_nothing_arrives():
    ctx = zmq.Context()
    sub = SameAudioSubscriber("inproc://same-sub-2", context=ctx)
    assert sub.recv(timeout_ms=50) is None
    sub.close()
    ctx.term()


def test_subscriber_ignores_non_same_topics():
    ctx = zmq.Context()
    pub = ctx.socket(zmq.PUB)
    pub.bind("inproc://same-sub-3")
    sub = SameAudioSubscriber("inproc://same-sub-3", context=ctx)

    header = {"site": "home", "channel": "WX5", "sample_rate_hz": 16000, "num_samples": 1}
    stt_frames = [b"stt.home.WX5", json.dumps(header).encode(), b"\x00"]

    # give the subscription time to propagate, then send an stt.* message
    # a few times -- it must never be delivered to a "same."-only SUB
    for _ in range(10):
        pub.send_multipart(stt_frames)
    assert sub.recv(timeout_ms=200) is None

    sub.close()
    pub.close(linger=0)
    ctx.term()
