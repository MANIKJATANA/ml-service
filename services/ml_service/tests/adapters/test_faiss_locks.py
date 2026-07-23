"""Per-school FAISS write-lock providers (BP8d, decisions/0052).

The in-process provider is tested always; the Redis provider gets a gated round-trip against
a real Redis (``ML_TEST_REDIS_URL``) — mutual exclusion for one school, concurrency across
schools, and fail-loud on a wait timeout — plus an always-on fail-loud test against a dead
port (no real Redis needed). Never touches the dev Redis destructively (unique keys, short
leases, always released).
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest
import pytest_asyncio

redis_asyncio = pytest.importorskip("redis.asyncio")

from ml_service.adapters.vector_index._locks import InProcLockProvider  # noqa: E402
from ml_service.adapters.vector_index._redis_locks import (  # noqa: E402
    RedisLockProvider,
)
from ml_service.domain.errors import LockAcquisitionError  # noqa: E402

# ---- in-process (Option A), always-on ----------------------------------


async def test_inproc_serializes_same_school() -> None:
    provider = InProcLockProvider()
    entered = asyncio.Event()

    async def contender() -> None:
        async with provider.acquire("s1"):
            entered.set()

    async with provider.acquire("s1"):
        task = asyncio.create_task(contender())
        await asyncio.sleep(0.02)
        assert not entered.is_set()  # blocked while we hold the school's lock
    await asyncio.wait_for(task, timeout=1.0)
    assert entered.is_set()  # proceeds once released


async def test_inproc_different_schools_do_not_block() -> None:
    provider = InProcLockProvider()

    async def enter_other() -> None:
        async with provider.acquire("s2"):
            pass

    async with provider.acquire("s1"):
        # A different school's lock is independent — no deadlock/block.
        await asyncio.wait_for(enter_other(), timeout=1.0)


async def test_inproc_returns_same_lock_per_school() -> None:
    provider = InProcLockProvider()
    assert provider.acquire("s1") is provider.acquire("s1")
    assert provider.acquire("s1") is not provider.acquire("s2")


# ---- Redis (Option B) fail-loud, always-on (dead port) -----------------


async def test_redis_release_failures_are_swallowed() -> None:
    # A release that can't reach Redis — or a lease that expired mid-write
    # (LockNotOwnedError) — must NOT propagate out of the context manager (best-effort
    # release; the lease TTL is the backstop). Covers both __aexit__ branches.
    from ml_service.adapters.vector_index._redis_locks import _RedisLockCtx
    from redis.exceptions import LockError, LockNotOwnedError

    class _Lock:
        def __init__(self, exc: Exception) -> None:
            self._exc = exc

        async def acquire(self) -> bool:
            return True

        async def release(self) -> None:
            raise self._exc

    errors: tuple[Exception, ...] = (
        LockNotOwnedError("lease expired"),  # type: ignore[no-untyped-call]
        LockError("release blip"),  # type: ignore[no-untyped-call]
    )
    for exc in errors:
        async with _RedisLockCtx(_Lock(exc), "s1", 1.0):  # type: ignore[arg-type]
            pass  # must exit cleanly, no exception


async def test_redis_fail_loud_on_unreachable() -> None:
    # Nothing listening -> the acquire must raise LockAcquisitionError, never write unlocked.
    bad = redis_asyncio.from_url(
        "redis://127.0.0.1:6390/0", socket_timeout=1, socket_connect_timeout=1
    )
    provider = RedisLockProvider(bad, lease_s=5.0, wait_s=1.0)
    try:
        with pytest.raises(LockAcquisitionError):
            async with provider.acquire("s1"):
                pass
    finally:
        await bad.aclose()


# ---- Redis (Option B) gated round-trip ---------------------------------

_URL = os.environ.get("ML_TEST_REDIS_URL")
_redis_gate = pytest.mark.skipif(not _URL, reason="ML_TEST_REDIS_URL not set")


@pytest_asyncio.fixture
async def client():  # type: ignore[no-untyped-def]
    c = redis_asyncio.from_url(_URL)
    yield c
    await c.aclose()


def _sid() -> str:
    return f"pytest-bp8d-{time.time_ns()}"


@_redis_gate
async def test_redis_same_school_mutual_exclusion(client) -> None:  # type: ignore[no-untyped-def]
    provider = RedisLockProvider(client, lease_s=30.0, wait_s=3.0)
    sid = _sid()
    entered = asyncio.Event()

    async def contender() -> None:
        async with provider.acquire(sid):
            entered.set()

    async with provider.acquire(sid):
        task = asyncio.create_task(contender())
        await asyncio.sleep(0.15)
        assert not entered.is_set()  # a second holder is blocked across the lock
    await asyncio.wait_for(task, timeout=3.0)
    assert entered.is_set()


@_redis_gate
async def test_redis_different_schools_concurrent(client) -> None:  # type: ignore[no-untyped-def]
    provider = RedisLockProvider(client, lease_s=30.0, wait_s=3.0)
    base = _sid()

    async def enter_other() -> None:
        async with provider.acquire(f"{base}-b"):
            pass

    async with provider.acquire(f"{base}-a"):
        await asyncio.wait_for(enter_other(), timeout=2.0)  # independent school, no block


@_redis_gate
async def test_redis_fail_loud_on_wait_timeout(client) -> None:  # type: ignore[no-untyped-def]
    provider = RedisLockProvider(client, lease_s=30.0, wait_s=0.2)
    sid = _sid()
    async with provider.acquire(sid):  # hold it
        with pytest.raises(LockAcquisitionError):
            async with provider.acquire(sid):  # can't get it within wait_s -> fail loud
                pass
