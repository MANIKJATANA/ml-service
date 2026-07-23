"""FAISS per-school vector index — the default ``VectorIndex`` adapter
(architecture §6, §7).

One ``IndexFlatIP`` per school (cosine == inner product on our L2-normalized
vectors). Tenant isolation is structural: each call names a ``school_id`` and only
that school's file is ever touched (NFR-3). Writes are serialized per school with
an in-process lock (Option A) and rebuild the whole index — brute-force but fine
at v1 scale (architecture §7.4). The read path re-checks ``meta.version`` and
reloads on staleness, and **fails loud** if the index's embedding-model version
doesn't match the configured embedder (never search a stale-model index, §7.3).

Multi-vector enrollment means one student owns several rows, so a raw top-k
search can return a student more than once; ``search`` over-fetches then collapses
to each student's best hit before returning ``top_k`` (see the ``VectorIndex``
port contract).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

import anyio
import faiss
import numpy as np

from ml_service.adapters.vector_index._faiss_cache import IndexCache, LoadedIndex
from ml_service.adapters.vector_index._index_store import IndexBlob, IndexStore
from ml_service.adapters.vector_index._locks import (
    InProcLockProvider,
    WriteLockProvider,
)
from ml_service.domain.errors import EmbeddingVersionMismatch, MLServiceError
from ml_service.domain.models import (
    EMBEDDING_DIM,
    SIMILARITY_METRIC,
    Candidate,
    Embedding,
)

_DEFAULT_OVERFETCH = 8


class FaissPerSchoolVectorIndex:
    """File-backed FAISS index per school with an in-memory LRU cache."""

    def __init__(
        self,
        store: IndexStore,
        embedder_version: str,
        *,
        cache_size: int = 32,
        overfetch: int = _DEFAULT_OVERFETCH,
        lock_provider: WriteLockProvider | None = None,
    ) -> None:
        self._store = store
        self._embedder_version = embedder_version
        self._cache = IndexCache(cache_size)
        self._overfetch = max(2, overfetch)
        # Serializes per-school writes. In-process (Option A) by default; the container
        # injects a Redis provider (Option B) for multi-replica enrollment (decisions/0052).
        self._locks = lock_provider or InProcLockProvider()

    # ---- write path (enrollment) ---------------------------------------

    async def upsert(
        self,
        school_id: str,
        student_id: str,
        embeddings: list[Embedding],
        metadata: Mapping[str, object],
    ) -> None:
        if not embeddings:
            return  # nothing to add; never wipe on empty (service also guards this)
        async with self._locks.acquire(school_id):
            loaded = await self._store.load(school_id)
            index_bytes, id_map, meta = await anyio.to_thread.run_sync(
                self._apply_upsert, loaded, student_id, embeddings
            )
            await self._store.save(school_id, index_bytes, id_map, meta)
            await self._cache.invalidate(school_id)

    async def delete(self, school_id: str, student_id: str) -> None:
        async with self._locks.acquire(school_id):
            loaded = await self._store.load(school_id)
            if loaded is None:
                return
            result = await anyio.to_thread.run_sync(
                self._apply_delete, loaded, student_id
            )
            if result is None:
                return  # student not present — nothing to do
            index_bytes, id_map, meta = result
            await self._store.save(school_id, index_bytes, id_map, meta)
            await self._cache.invalidate(school_id)

    def _apply_upsert(
        self,
        loaded: IndexBlob | None,
        student_id: str,
        embeddings: list[Embedding],
    ) -> tuple[bytes, list[str], dict[str, object]]:
        vecs, labels, prev_meta = self._reconstruct(loaded)
        keep = [lbl != student_id for lbl in labels]  # replace-not-append (FR-E3)
        kept_vecs = vecs[keep] if labels else vecs
        kept_labels = [lbl for lbl, k in zip(labels, keep, strict=True) if k]
        add = np.asarray([e.vector for e in embeddings], dtype=np.float32)
        all_vecs = np.vstack([kept_vecs, add]) if len(kept_vecs) else add
        all_labels = kept_labels + [student_id] * len(embeddings)
        return self._serialize(all_vecs, all_labels, prev_meta)

    def _apply_delete(
        self, loaded: IndexBlob, student_id: str
    ) -> tuple[bytes, list[str], dict[str, object]] | None:
        vecs, labels, prev_meta = self._reconstruct(loaded)
        if student_id not in labels:
            return None
        keep = [lbl != student_id for lbl in labels]
        kept_vecs = vecs[keep]
        kept_labels = [lbl for lbl, k in zip(labels, keep, strict=True) if k]
        return self._serialize(kept_vecs, kept_labels, prev_meta)

    def _reconstruct(
        self, loaded: IndexBlob | None
    ) -> tuple[np.ndarray, list[str], dict[str, object] | None]:
        """Recover (vectors, labels, prev_meta) from a stored blob. Rebuilding
        from reconstructed vectors sidesteps FAISS row-id shifting on removal."""
        empty = np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        if loaded is None:
            return empty, [], None
        index_bytes, id_map, meta = loaded
        index = self._deserialize(index_bytes)
        n = int(index.ntotal)
        if n != len(id_map):  # corrupt/mismatched files — never rebuild from them
            raise MLServiceError(
                f"corrupt index: ntotal={n} != id_map entries={len(id_map)}"
            )
        if n == 0:
            return empty, [], meta
        vecs = np.asarray(index.reconstruct_n(0, n), dtype=np.float32)
        return vecs, list(id_map), meta

    def _serialize(
        self,
        vecs: np.ndarray,
        labels: list[str],
        prev_meta: dict[str, object] | None,
    ) -> tuple[bytes, list[str], dict[str, object]]:
        index = faiss.IndexFlatIP(EMBEDDING_DIM)
        if len(vecs):
            index.add(np.ascontiguousarray(vecs, dtype=np.float32))
        raw = faiss.serialize_index(index)
        prev_version = int(cast("int", prev_meta.get("version", 0))) if prev_meta else 0
        meta: dict[str, object] = {
            "embedding_model_version": self._embedder_version,
            "dim": EMBEDDING_DIM,
            "metric": SIMILARITY_METRIC,
            "version": prev_version + 1,  # bumped on every write (cache key, §7.1)
            "count": len(labels),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        return bytes(raw.tobytes()), labels, meta

    # ---- read path (inference) -----------------------------------------

    async def search(
        self, school_id: str, embedding: Embedding, top_k: int
    ) -> list[Candidate]:
        entry = await self._get_fresh(school_id)
        if entry is None or int(entry.index.ntotal) == 0:
            return []
        q = np.asarray(embedding.vector, dtype=np.float32).reshape(1, EMBEDDING_DIM)
        k = min(int(entry.index.ntotal), max(top_k * self._overfetch, top_k))
        scores, idxs = await anyio.to_thread.run_sync(entry.index.search, q, k)
        best: dict[str, float] = {}
        for score, idx in zip(scores[0], idxs[0], strict=True):
            if idx < 0:
                continue
            sid = entry.id_map[int(idx)]
            score_f = float(score)
            if sid not in best or score_f > best[sid]:
                best[sid] = score_f  # collapse to each student's best hit
        ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
        return [Candidate(sid, score) for sid, score in ranked]

    async def _get_fresh(self, school_id: str) -> LoadedIndex | None:
        """Return a cache entry whose ``meta.version`` matches the store, loading
        or reloading as needed. Fails loud on an embedding-model-version mismatch."""
        remote_meta = await self._store.read_meta(school_id)
        if remote_meta is None:
            return None  # no index for this school yet
        self._check_model_version(remote_meta)
        cached = await self._cache.get(school_id)
        if cached is not None and cached.meta.get("version") == remote_meta.get(
            "version"
        ):
            return cached
        loaded = await self._store.load(school_id)
        if loaded is None:
            return None
        index_bytes, id_map, meta = loaded
        self._check_model_version(meta)
        index = await anyio.to_thread.run_sync(self._deserialize, index_bytes)
        entry = LoadedIndex(index=index, id_map=list(id_map), meta=meta)
        await self._cache.put(school_id, entry)
        return entry

    def _check_model_version(self, meta: Mapping[str, object]) -> None:
        stored = meta.get("embedding_model_version")
        if stored != self._embedder_version:
            raise EmbeddingVersionMismatch(
                f"index embedding_model_version={stored!r} != configured embedder "
                f"{self._embedder_version!r}; refusing to search a stale-model index"
            )

    @staticmethod
    def _deserialize(index_bytes: bytes) -> Any:
        arr = np.frombuffer(index_bytes, dtype=np.uint8).copy()
        return faiss.deserialize_index(arr)
