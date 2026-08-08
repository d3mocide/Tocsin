"""Redis-persisted circuit breaker for LiteLLM stage-2 calls (design doc
§7: "Circuit breaker after N consecutive failures (state in Redis)").

Opens after `failure_threshold` consecutive failures; while open, every
call is skipped without even attempting LiteLLM, for `cooldown_seconds`.
Recovery is TTL-driven, not a dedicated half-open state: once the open
marker expires from Redis, the next call is simply allowed to try again --
if it fails, `record_failure` re-opens the breaker immediately (the
threshold is already met); if it succeeds, `record_success` resets the
failure counter to zero. This is the design doc's own literal exit
criterion (roadmap.md): "circuit breaker opens after N consecutive
failures and recovers."
"""

from __future__ import annotations

DEFAULT_FAILURE_THRESHOLD = 5
DEFAULT_COOLDOWN_SECONDS = 300  # 5 min

FAILURE_COUNT_KEY = "tocsin:dispatch:litellm:failures"
OPEN_KEY = "tocsin:dispatch:litellm:open"


class CircuitBreaker:
    def __init__(
        self,
        redis_client,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
    ):
        self._redis = redis_client
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds

    def is_open(self) -> bool:
        return bool(self._redis.exists(OPEN_KEY))

    def record_failure(self) -> None:
        count = self._redis.incr(FAILURE_COUNT_KEY)
        if count >= self._failure_threshold:
            self._redis.set(OPEN_KEY, "1", ex=self._cooldown_seconds)

    def record_success(self) -> None:
        self._redis.delete(FAILURE_COUNT_KEY)
