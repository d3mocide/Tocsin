from dispatcher.idempotency import IdempotencyStore, idempotency_key


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.calls = []

    def set(self, key, value, nx=None, ex=None):
        self.calls.append({"key": key, "value": value, "nx": nx, "ex": ex})
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True


def test_first_claim_succeeds():
    redis = FakeRedis()
    store = IdempotencyStore(redis)
    assert store.claim("ZCZC-WXR-TOR-041051+0045-2202132-KPQR/NWS-", stage="1") is True


def test_second_claim_of_the_same_header_and_stage_fails():
    redis = FakeRedis()
    store = IdempotencyStore(redis)
    header = "ZCZC-WXR-TOR-041051+0045-2202132-KPQR/NWS-"
    store.claim(header, stage="1")
    assert store.claim(header, stage="1") is False


def test_claim_survives_a_new_store_instance_against_the_same_redis():
    # Simulates a dispatcher restart: a fresh IdempotencyStore, same
    # underlying Redis data.
    redis = FakeRedis()
    header = "ZCZC-WXR-TOR-041051+0045-2202132-KPQR/NWS-"
    IdempotencyStore(redis).claim(header, stage="1")
    assert IdempotencyStore(redis).claim(header, stage="1") is False


def test_different_stage_is_a_different_key():
    redis = FakeRedis()
    store = IdempotencyStore(redis)
    header = "ZCZC-WXR-TOR-041051+0045-2202132-KPQR/NWS-"
    assert store.claim(header, stage="1") is True
    assert store.claim(header, stage="2") is True


def test_claim_sets_a_ttl():
    redis = FakeRedis()
    IdempotencyStore(redis, ttl_seconds=3600).claim("header", stage="1")
    assert redis.calls[0]["ex"] == 3600
    assert redis.calls[0]["nx"] is True


def test_idempotency_key_is_stable_for_the_same_inputs():
    assert idempotency_key("header-text", "1") == idempotency_key("header-text", "1")
    assert idempotency_key("header-text", "1") != idempotency_key("header-text", "2")
    assert idempotency_key("header-a", "1") != idempotency_key("header-b", "1")
