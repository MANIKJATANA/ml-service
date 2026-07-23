"""Option B: a per-school Redis distributed write lock (BP8d, decisions/0052).

Lets enrollment run **multi-replica** — a per-school Redis lock (``SET NX PX`` + a Lua
compare-and-del release, via ``redis.asyncio``'s ``Lock``) serializes each school's index
read-modify-write across every replica, while different schools proceed in parallel. Reuses
the shared Redis client the container already builds for the queue.

**Fail-loud** (the deliberate opposite of the BP8c rate limiter's fail-open): a lock-backend
outage or an acquire that exceeds ``wait_s`` raises ``LockAcquisitionError`` — the enroll
fails (retryable; the backend records ``enrollment_status=failed`` and never blocks account
creation), **never** a silent unlocked write, because an unlocked FAISS write under
concurrency risks a lost enrollment (correctness > availability here).
"""

from __future__ import annotations

from types import TracebackType
from typing import TYPE_CHECKING

import structlog
from redis.exceptions import LockNotOwnedError, RedisError

from ml_service.domain.errors import LockAcquisitionError

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from redis.asyncio.lock import Lock

_log = structlog.get_logger(__name__)


class _RedisLockCtx:
    """Async CM around a redis ``Lock``: fail-loud on enter, best-effort release on exit."""

    def __init__(self, lock: Lock, school_id: str, wait_s: float) -> None:
        self._lock = lock
        self._school_id = school_id
        self._wait_s = wait_s

    async def __aenter__(self) -> None:
        try:
            acquired = await self._lock.acquire()
        except (RedisError, OSError) as exc:
            raise LockAcquisitionError(
                f"write-lock backend error for school {self._school_id}: {exc}"
            ) from exc
        if not acquired:
            raise LockAcquisitionError(
                f"timed out acquiring the write lock for school {self._school_id} "
                f"after {self._wait_s}s"
            )

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        try:
            await self._lock.release()
        except LockNotOwnedError:
            # The lease expired WHILE we held it (the write outran ML_FAISS_LOCK_LEASE_S) —
            # another replica could have acquired + written concurrently. We can't un-corrupt
            # here; surface it loudly so the lease gets raised (decisions/0052, honest limit).
            _log.error(
                "faiss_write_lock_lease_lost",
                school_id=self._school_id,
                hint="raise ML_FAISS_LOCK_LEASE_S above the slowest index rebuild+upload",
            )
        except (RedisError, OSError):
            # A transient release blip — the lease TTL is the backstop.
            _log.warning("faiss_write_lock_release_failed", school_id=self._school_id)
        return False


class RedisLockProvider:
    """``WriteLockProvider`` over a shared Redis client (config ``ml_faiss_lock_impl=redis``).

    ``lease_s`` is the lock's auto-expiry ceiling (must exceed the slowest index
    rebuild+upload so a live holder is never evicted — see the lease-loss honest limit in
    decisions/0052); ``wait_s`` is how long a contender blocks before failing loud.

    NB: redis-py's ``Lock`` stores its release token in thread-local storage, so acquire and
    release must run on the **same** thread. They do — the FAISS adapter awaits both on the
    event-loop thread and only offloads the pure rebuild to a worker thread — so this holds.
    """

    def __init__(self, redis: Redis, *, lease_s: float, wait_s: float) -> None:
        self._redis = redis
        self._lease_s = lease_s
        self._wait_s = wait_s

    def acquire(self, school_id: str) -> _RedisLockCtx:
        lock = self._redis.lock(
            f"faiss:lock:{school_id}",
            timeout=self._lease_s,
            blocking=True,
            blocking_timeout=self._wait_s,
        )
        return _RedisLockCtx(lock, school_id, self._wait_s)
