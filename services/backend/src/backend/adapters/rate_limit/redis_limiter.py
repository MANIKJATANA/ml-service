"""Redis fixed-window rate limiter (BP8c, decisions/0051).

Cross-replica-correct counters in Redis: ``INCR`` a per-window key and set ``EXPIRE`` so it
self-cleans after the window. The window index is derived from **wall-clock** time (not
``monotonic`` — that differs per host) so replicas share the same window. Reuses the shared
Redis (``BE_REDIS_URL``) like ``redis_producer.py``.

**Fail-open:** a Redis error/outage returns ``allowed=True`` — a limiter failure must never
take the API down (availability over strict enforcement).
"""

from __future__ import annotations

import time

from redis.asyncio import Redis
from redis.exceptions import RedisError

from backend.domain.models import RateLimitResult


class RedisRateLimiter:
    """``RateLimiter`` over a shared Redis (``INCR`` + ``EXPIRE`` per window)."""

    def __init__(self, redis_url: str) -> None:
        # Lazy client — construction never connects; the first acquire connects.
        self._redis: Redis = Redis.from_url(redis_url)

    async def acquire(
        self, key: str, *, limit: int, window_s: int
    ) -> RateLimitResult:
        now = time.time()
        window = int(now // window_s)
        redis_key = f"ratelimit:{key}:{window}"
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incr(redis_key)
                pipe.expire(redis_key, window_s)
                count, _ = await pipe.execute()
        except (RedisError, OSError):
            return RateLimitResult(allowed=True, retry_after_s=0)  # fail-open
        if int(count) > limit:
            retry_after = window_s - int(now % window_s)
            return RateLimitResult(allowed=False, retry_after_s=max(1, retry_after))
        return RateLimitResult(allowed=True, retry_after_s=0)

    async def aclose(self) -> None:
        await self._redis.aclose()
