import json

import numpy as np
import zmq

from sdr_rx.bus import TOPIC_SAME, TOPIC_STT, Publisher


def _recv_with_retry(sub: zmq.Socket, send_fn, timeout_ms: int = 200, attempts: int = 25):
    """inproc PUB/SUB has no slow-joiner delay, but the SUB's subscription
    still has to propagate before a send is visible to it -- retry the send
    until the poll succeeds instead of relying on a fixed sleep."""
    for _ in range(attempts):
        send_fn()
        if sub.poll(timeout_ms):
            return sub.recv_multipart()
    raise AssertionError("no message received from publisher")


def test_publish_sends_topic_header_and_pcm():
    ctx = zmq.Context()
    pub = Publisher("inproc://test-bus-1", context=ctx)
    sub = ctx.socket(zmq.SUB)
    sub.connect("inproc://test-bus-1")
    sub.setsockopt(zmq.SUBSCRIBE, b"")

    pcm = np.array([1, -1, 2, -2], dtype=np.int16)
    frames = _recv_with_retry(sub, lambda: pub.publish(TOPIC_SAME, "WX5", 22050, pcm))

    topic, header_bytes, payload = frames
    assert topic == b"same.WX5"
    header = json.loads(header_bytes)
    assert header["channel"] == "WX5"
    assert header["sample_rate_hz"] == 22050
    assert header["dtype"] == "s16le"
    assert header["num_samples"] == 4
    np.testing.assert_array_equal(np.frombuffer(payload, dtype=np.int16), pcm)

    pub.close()
    sub.close()
    ctx.term()


def test_sequence_number_increments_across_publishes():
    ctx = zmq.Context()
    pub = Publisher("inproc://test-bus-2", context=ctx)
    sub = ctx.socket(zmq.SUB)
    sub.connect("inproc://test-bus-2")
    sub.setsockopt(zmq.SUBSCRIBE, b"")

    pcm = np.array([0], dtype=np.int16)
    first = _recv_with_retry(sub, lambda: pub.publish(TOPIC_STT, "WX1", 16000, pcm))
    second = _recv_with_retry(sub, lambda: pub.publish(TOPIC_STT, "WX1", 16000, pcm))

    assert json.loads(first[1])["seq"] == 0
    assert json.loads(second[1])["seq"] == 1

    pub.close()
    sub.close()
    ctx.term()


def test_different_channels_get_distinct_topics():
    ctx = zmq.Context()
    pub = Publisher("inproc://test-bus-3", context=ctx)
    sub = ctx.socket(zmq.SUB)
    sub.connect("inproc://test-bus-3")
    sub.setsockopt(zmq.SUBSCRIBE, b"")

    pcm = np.array([0], dtype=np.int16)
    frames = _recv_with_retry(sub, lambda: pub.publish(TOPIC_SAME, "WX3", 22050, pcm))
    assert frames[0] == b"same.WX3"

    pub.close()
    sub.close()
    ctx.term()
