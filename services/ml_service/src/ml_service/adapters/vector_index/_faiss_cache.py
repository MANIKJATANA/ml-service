"""Per-worker in-memory cache of loaded FAISS indexes (architecture §7.2).

An LRU of ``school_id → LoadedIndex``; the source of truth is the index store, so
eviction just drops the entry. A separate per-school ``asyncio.Lock`` serializes
writes within the process (FAISS Option A, architecture §7.4) and outlives cache
eviction so it stays the fleet-wide write lock under a single-replica enrollment
deployment.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any


@dataclass
class LoadedIndex:
    """A cached, in-memory FAISS index plus its row→student map and last-seen meta.

    Mutations are serialized by the cache's per-school write lock
    (``IndexCache.write_lock``), so no per-entry lock is needed here."""

    index: Any  # faiss.Index (no type stubs)
    id_map: list[str]
    meta: dict[str, object]


class IndexCache:
    """LRU of loaded indexes + a persistent per-school write lock registry."""

    def __init__(self, max_size: int = 32) -> None:
        if max_size < 1:
            raise ValueError("cache max_size must be >= 1")
        self._max = max_size
        self._entries: OrderedDict[str, LoadedIndex] = OrderedDict()
        self._write_locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    def write_lock(self, school_id: str) -> asyncio.Lock:
        """Return the school's write lock, creating it on first use. Persistent:
        it must not be evicted with the cache entry (it's the serialization point
        for concurrent enrollments). Lock creation has no ``await`` so it's atomic
        under the event loop."""
        lock = self._write_locks.get(school_id)
        if lock is None:
            lock = asyncio.Lock()
            self._write_locks[school_id] = lock
        return lock

    async def get(self, school_id: str) -> LoadedIndex | None:
        async with self._guard:
            entry = self._entries.get(school_id)
            if entry is not None:
                self._entries.move_to_end(school_id)
            return entry

    async def put(self, school_id: str, entry: LoadedIndex) -> None:
        async with self._guard:
            self._entries[school_id] = entry
            self._entries.move_to_end(school_id)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)  # evict least-recently-used

    async def invalidate(self, school_id: str) -> None:
        async with self._guard:
            self._entries.pop(school_id, None)
