"""In-memory fixed-window rate limiter (BP8c, decisions/0051).

Per-process (per-replica) counters: under multiple backend replicas each holds its own, so
the effective limit is N× the configured value — the Redis adapter is the cross-replica
option. One entry per key: ``key -> (window, count)``, reset when the window rolls over
(so the map is bounded by the number of distinct keys ever seen — one per tenant + the two
fixed tiers). The read+increment is synchronous (no ``await`` between them), so it's atomic
within the single asyncio event loop — no lock needed.

Fixed-window (not sliding): a client can burst up to 2× the limit across a window boundary
(``limit`` at the end of one window + ``limit`` at the start of the next). Accepted for a
coarse throttle; a sliding/token-bucket window is the scale-up. The Redis adapter shares the
same semantics.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from backend.domain.models import RateLimitResult


class InMemoryRateLimiter:
    """``RateLimiter`` backed by an in-process dict. ``now`` is injectable for tests."""

    def __init__(self, *, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._buckets: dict[str, tuple[int, int]] = {}  # key -> (window, count)

    async def acquire(
        self, key: str, *, limit: int, window_s: int
    ) -> RateLimitResult:
        now = self._now()
        window = int(now // window_s)
        w, count = self._buckets.get(key, (window, 0))
        if w != window:  # a new window opened — reset this key's counter
            count = 0
        count += 1
        self._buckets[key] = (window, count)
        if count > limit:
            retry_after = window_s - int(now % window_s)
            return RateLimitResult(allowed=False, retry_after_s=max(1, retry_after))
        return RateLimitResult(allowed=True, retry_after_s=0)
