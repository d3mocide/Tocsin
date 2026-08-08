"""Stage 2 tests, including roadmap.md's literal Phase 7 exit criteria:
"killing the LiteLLM endpoint mid-run degrades stage 2 silently with
stage 1 still delivered" and "circuit breaker opens after N consecutive
failures and recovers."

"Stage 1 still delivered" isn't re-asserted per test here -- it's true by
construction, not something a single assertion proves: `Stage2Dispatcher`
is an entirely separate class from `Stage1Dispatcher` (see
`test_service.py`), consuming a different Redis stream via a different
`AlertStreamConsumer` instance (`__init__.py`), sharing no call path that
a stage-2 failure could block. What *is* directly testable here, and is
tested below, is stage 2's own half of that promise: a LiteLLM failure
never raises out of `handle()` and never touches the egress layer.
"""

from __future__ import annotations

from dispatcher.circuit_breaker import CircuitBreaker
from dispatcher.egress.dispatch import EgressResult
from dispatcher.idempotency import IdempotencyStore
from dispatcher.litellm_client import LiteLLMClient
from dispatcher.models import TranscriptIn
from dispatcher.service import Stage2Dispatcher


class FakeRedis:
    def __init__(self):
        self.store = {}

    def set(self, key, value, nx=None, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def exists(self, key):
        return 1 if key in self.store else 0

    def incr(self, key):
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]

    def delete(self, key):
        self.store.pop(key, None)


class FakeEgress:
    def __init__(self, result=None, raises=None):
        self.result = result or EgressResult(delivered=True, path="serial")
        self.raises = raises
        self.sent = []

    def send(self, text):
        self.sent.append(text)
        if self.raises:
            raise self.raises
        return self.result


class FakeLiteLLM:
    def __init__(self, response=None, raises=None):
        self.response = response
        self.raises = raises
        self.calls = []

    def compress(self, text, max_bytes):
        self.calls.append(text)
        if self.raises:
            raise self.raises
        return self.response


def _transcript(tier="A", text="a tornado touched down near downtown", passed_guard=True, raw_header="header-1"):
    return TranscriptIn(
        site="home",
        channel="WX5",
        event_code="TOR",
        tier=tier,
        fips_codes=("041051",),
        raw_header=raw_header,
        text=text,
        passed_guard=passed_guard,
        guard_reason=None,
    )


def _dispatcher(redis=None, litellm=None, egress=None, failure_threshold=5, cooldown_seconds=300):
    redis = redis or FakeRedis()
    return Stage2Dispatcher(
        idempotency=IdempotencyStore(redis),
        circuit_breaker=CircuitBreaker(redis, failure_threshold=failure_threshold, cooldown_seconds=cooldown_seconds),
        litellm_client=litellm or FakeLiteLLM(response="Tornado confirmed near downtown."),
        egress=egress or FakeEgress(),
    )


def test_tier_b_never_calls_litellm():
    litellm = FakeLiteLLM(response="should not be used")
    outcome = _dispatcher(litellm=litellm).handle(_transcript(tier="B"))
    assert outcome.reason == "skipped_not_tier_a"
    assert litellm.calls == []


def test_failed_transcript_guard_never_calls_litellm():
    litellm = FakeLiteLLM(response="should not be used")
    outcome = _dispatcher(litellm=litellm).handle(_transcript(passed_guard=False, text=""))
    assert outcome.reason == "skipped_no_transcript"
    assert litellm.calls == []


def test_successful_enrichment_sends_the_impact_clause():
    egress = FakeEgress()
    outcome = _dispatcher(egress=egress).handle(_transcript())
    assert outcome.sent is True
    assert outcome.reason == "serial"
    assert egress.sent == ["Tornado confirmed near downtown."]


def test_litellm_failure_degrades_silently_without_touching_egress():
    egress = FakeEgress()
    litellm = FakeLiteLLM(raises=RuntimeError("connection refused"))
    outcome = _dispatcher(litellm=litellm, egress=egress).handle(_transcript())

    assert outcome.sent is False
    assert outcome.reason == "skipped_litellm_failure"
    assert egress.sent == []  # stage 1's own delivery is entirely untouched by this


def test_bad_output_from_litellm_is_rejected_and_never_sent():
    egress = FakeEgress()
    litellm = FakeLiteLLM(response="line one\nline two")  # violates the no-newlines guard
    outcome = _dispatcher(litellm=litellm, egress=egress).handle(_transcript())

    assert outcome.sent is False
    assert outcome.reason.startswith("skipped_output_guard")
    assert egress.sent == []


def test_second_identical_transcript_is_not_re_enriched_or_re_sent():
    redis = FakeRedis()
    litellm = FakeLiteLLM(response="Tornado confirmed near downtown.")
    egress = FakeEgress()
    dispatcher = _dispatcher(redis=redis, litellm=litellm, egress=egress)

    dispatcher.handle(_transcript())
    outcome = dispatcher.handle(_transcript())

    assert outcome.reason == "skipped_already_sent"
    assert len(litellm.calls) == 1  # the early already_claimed() check skipped the second LLM call entirely
    assert len(egress.sent) == 1


def test_circuit_breaker_opens_after_n_consecutive_failures_and_then_recovers():
    redis = FakeRedis()
    litellm = FakeLiteLLM(raises=RuntimeError("connection refused"))
    dispatcher = _dispatcher(redis=redis, litellm=litellm, failure_threshold=3, cooldown_seconds=60)

    outcomes = [
        dispatcher.handle(_transcript(raw_header=f"header-{i}"))
        for i in range(3)
    ]
    assert [o.reason for o in outcomes] == ["skipped_litellm_failure"] * 3

    # breaker is now open -- the 4th call must not even attempt LiteLLM
    outcome = dispatcher.handle(_transcript(raw_header="header-4"))
    assert outcome.reason == "skipped_circuit_open"
    assert len(litellm.calls) == 3  # not 4 -- the open breaker short-circuited before calling compress()

    # simulate the cooldown TTL lapsing, then recovery on the next success
    from dispatcher.circuit_breaker import OPEN_KEY

    redis.store.pop(OPEN_KEY, None)
    recovering_litellm = FakeLiteLLM(response="Tornado confirmed near downtown.")
    recovered_dispatcher = _dispatcher(redis=redis, litellm=recovering_litellm, failure_threshold=3, cooldown_seconds=60)

    outcome = recovered_dispatcher.handle(_transcript(raw_header="header-5"))
    assert outcome.sent is True
    assert outcome.reason == "serial"
