from dispatcher.rate_limit import TokenBucket


def test_burst_capacity_is_available_immediately():
    bucket = TokenBucket(capacity=3, refill_per_hour=6.0, now=0.0)
    assert bucket.try_acquire(now=0.0) is True
    assert bucket.try_acquire(now=0.0) is True
    assert bucket.try_acquire(now=0.0) is True


def test_fourth_immediate_request_is_denied():
    bucket = TokenBucket(capacity=3, refill_per_hour=6.0, now=0.0)
    for _ in range(3):
        bucket.try_acquire(now=0.0)
    assert bucket.try_acquire(now=0.0) is False


def test_tokens_refill_over_time():
    bucket = TokenBucket(capacity=3, refill_per_hour=6.0, now=0.0)  # 1 token per 600s
    for _ in range(3):
        bucket.try_acquire(now=0.0)
    assert bucket.try_acquire(now=599.0) is False
    assert bucket.try_acquire(now=601.0) is True


def test_refill_never_exceeds_capacity():
    bucket = TokenBucket(capacity=3, refill_per_hour=6.0, now=0.0)
    # A very long idle period shouldn't bank more than `capacity` tokens.
    assert bucket.try_acquire(now=100_000.0) is True
    assert bucket.try_acquire(now=100_000.0) is True
    assert bucket.try_acquire(now=100_000.0) is True
    assert bucket.try_acquire(now=100_000.0) is False
