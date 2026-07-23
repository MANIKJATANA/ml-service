"""Per-school FAISS write-lock providers (BP8d, decisions/0052).

Enrollment serializes each school's index read-modify-write. Option A is an in-process
``asyncio.Lock`` (the fleet-wide lock *only* under a single-replica enrollment deployment);
Option B (``_redis_locks.py``) is a Redis distributed lock so enrollment can scale to
multiple replicas. The FAISS adapter holds ``acquire(school_id)`` across the whole critical
section; different schools never contend. This is an adapter-internal seam — ``domain`` /
``orchestration`` never touch it (the FAISS adapter owns the lock), so it stays out of
``domain/ports.py`` and the layering invariant holds.
"""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol


class WriteLockProvider(Protocol):
    """Yields a mutual-exclusion context manager for one school's index writes."""

    def acquire(self, school_id: str) -> AbstractAsyncContextManager[Any]: ...


class InProcLockProvider:
    """Option A: a per-school in-process ``asyncio.Lock`` (config default ``inproc``).

    The registry is a container singleton, so it outlives the FAISS LRU cache (a lock must
    not be evicted while it's serializing writes). Lock creation has no ``await``, so it's
    atomic under the event loop — no guard needed."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def acquire(self, school_id: str) -> asyncio.Lock:
        lock = self._locks.get(school_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[school_id] = lock
        return lock
