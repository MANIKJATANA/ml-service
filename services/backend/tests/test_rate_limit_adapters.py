"""Rate-limiter adapters (BP8c, decisions/0051).

The in-memory limiter is tested with an injected clock (no real sleep); the Redis limiter
gets a gated round-trip against a real Redis (skipped unless BE_TEST_REDIS_URL is set — never
the dev Redis by accident, and it only writes short-lived, uniquely-keyed counters).
"""

from __future__ import annotations

import os
import time

import pytest
from backend.adapters.rate_limit.memory import InMemoryRateLimiter


async def test_memory_allows_up_to_limit_then_blocks() -> None:
    clock = [1000.0]
    rl = InMemoryRateLimiter(now=lambda: clock[0])
    for _ in range(3):
        assert (await rl.acquire("k", limit=3, window_s=60)).allowed
    blocked = await rl.acquire("k", limit=3, window_s=60)
    assert blocked.allowed is False
    assert 0 < blocked.retry_after_s <= 60  # a sane retry within the window


async def test_memory_resets_after_window() -> None:
    clock = [1000.0]
    rl = InMemoryRateLimiter(now=lambda: clock[0])
    for _ in range(3):
        await rl.acquire("k", limit=3, window_s=60)
    assert (await rl.acquire("k", limit=3, window_s=60)).allowed is False
    clock[0] += 60  # roll into the next window
    assert (await rl.acquire("k", limit=3, window_s=60)).allowed is True


async def test_memory_keys_are_independent() -> None:
    clock = [0.0]
    rl = InMemoryRateLimiter(now=lambda: clock[0])
    assert (await rl.acquire("a", limit=1, window_s=60)).allowed is True
    assert (await rl.acquire("a", limit=1, window_s=60)).allowed is False
    # A different key has its own bucket.
    assert (await rl.acquire("b", limit=1, window_s=60)).allowed is True


# ---- gated real-Redis round-trip ---------------------------------------

_REDIS = os.environ.get("BE_TEST_REDIS_URL")
_redis_gate = pytest.mark.skipif(_REDIS is None, reason="BE_TEST_REDIS_URL not set")


@_redis_gate
async def test_redis_limiter_round_trip() -> None:
    from backend.adapters.rate_limit.redis_limiter import RedisRateLimiter

    assert _REDIS is not None
    rl = RedisRateLimiter(_REDIS)
    # A unique key per run (auto-expires after the window) so we never touch other data.
    key = f"pytest-bp8c:{time.time_ns()}"
    try:
        for _ in range(2):
            assert (await rl.acquire(key, limit=2, window_s=60)).allowed is True
        blocked = await rl.acquire(key, limit=2, window_s=60)
        assert blocked.allowed is False and blocked.retry_after_s > 0
        # A different key is independent.
        other = await rl.acquire(f"{key}:other", limit=2, window_s=60)
        assert other.allowed is True
    finally:
        await rl.aclose()


@_redis_gate
async def test_redis_limiter_fails_open_on_bad_url() -> None:
    from backend.adapters.rate_limit.redis_limiter import RedisRateLimiter

    # An unreachable Redis must fail-open (allow), never raise.
    rl = RedisRateLimiter("redis://127.0.0.1:6390/0")  # nothing listening
    try:
        result = await rl.acquire("k", limit=1, window_s=60)
        assert result.allowed is True
    finally:
        await rl.aclose()


async def test_redis_limiter_fails_open_on_operation_error() -> None:
    # Always-on (no real Redis): a RedisError raised mid-operation (during execute) must
    # fail-open — the hot-path safety property the gated test can't cover in default CI.
    from backend.adapters.rate_limit.redis_limiter import RedisRateLimiter
    from redis.exceptions import RedisError

    class _FakePipe:
        def incr(self, key: str) -> None: ...
        def expire(self, key: str, ttl: int) -> None: ...
        async def execute(self) -> object:
            raise RedisError("boom")
        async def __aenter__(self) -> _FakePipe:
            return self
        async def __aexit__(self, *exc: object) -> bool:
            return False

    class _FakeRedis:
        def pipeline(self, transaction: bool = True) -> _FakePipe:
            return _FakePipe()

    rl = RedisRateLimiter("redis://unused")  # lazy client, never connects
    rl._redis = _FakeRedis()  # type: ignore[assignment]
    result = await rl.acquire("k", limit=1, window_s=60)
    assert result.allowed is True and result.retry_after_s == 0
