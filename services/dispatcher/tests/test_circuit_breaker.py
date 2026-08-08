from dispatcher.circuit_breaker import CircuitBreaker, FAILURE_COUNT_KEY, OPEN_KEY


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.ttls = {}

    def exists(self, key):
        return 1 if key in self.store else 0

    def incr(self, key):
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    def set(self, key, value, ex=None):
        self.store[key] = value
        self.ttls[key] = ex
        return True

    def delete(self, key):
        self.store.pop(key, None)

    def expire_open_key(self):
        """Test helper simulating the OPEN_KEY's TTL lapsing."""
        self.store.pop(OPEN_KEY, None)


def test_closed_by_default():
    breaker = CircuitBreaker(FakeRedis())
    assert breaker.is_open() is False


def test_stays_closed_under_the_threshold():
    redis = FakeRedis()
    breaker = CircuitBreaker(redis, failure_threshold=5)
    for _ in range(4):
        breaker.record_failure()
    assert breaker.is_open() is False


def test_opens_after_the_threshold_is_reached():
    redis = FakeRedis()
    breaker = CircuitBreaker(redis, failure_threshold=5)
    for _ in range(5):
        breaker.record_failure()
    assert breaker.is_open() is True


def test_success_resets_the_failure_counter():
    redis = FakeRedis()
    breaker = CircuitBreaker(redis, failure_threshold=5)
    for _ in range(4):
        breaker.record_failure()
    breaker.record_success()
    assert redis.store.get(FAILURE_COUNT_KEY, 0) == 0
    breaker.record_failure()
    assert breaker.is_open() is False  # only 1 failure since the reset


def test_recovers_once_the_open_marker_expires():
    redis = FakeRedis()
    breaker = CircuitBreaker(redis, failure_threshold=3, cooldown_seconds=60)
    for _ in range(3):
        breaker.record_failure()
    assert breaker.is_open() is True

    redis.expire_open_key()  # simulate the cooldown TTL lapsing

    assert breaker.is_open() is False
    breaker.record_success()
    assert redis.store.get(FAILURE_COUNT_KEY, 0) == 0


def test_open_uses_the_configured_cooldown_as_the_ttl():
    redis = FakeRedis()
    breaker = CircuitBreaker(redis, failure_threshold=1, cooldown_seconds=123)
    breaker.record_failure()
    assert redis.ttls[OPEN_KEY] == 123
