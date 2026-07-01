"""FAISS per-school vector index adapter — runs on CPU everywhere (faiss-cpu).

Uses synthetic orthonormal 512-d vectors so cosine scores are exactly 1.0 (same
direction) or 0.0 (orthogonal), letting us assert search/collapse/replace/delete
and the fail-loud version check precisely.
"""

from __future__ import annotations

import pytest
from fakes import normalized
from ml_service.adapters.vector_index._index_store import LocalFsIndexStore
from ml_service.adapters.vector_index.faiss_per_school import FaissPerSchoolVectorIndex
from ml_service.domain.errors import EmbeddingVersionMismatch

EMB_V = "emb-test-1"


def _make(tmp_path: object, version: str = EMB_V, **kwargs: object) -> FaissPerSchoolVectorIndex:
    store = LocalFsIndexStore(str(tmp_path))
    return FaissPerSchoolVectorIndex(store, version, **kwargs)  # type: ignore[arg-type]


async def test_search_on_missing_index_returns_empty(tmp_path: object) -> None:
    idx = _make(tmp_path)
    assert await idx.search("s1", normalized([1.0]), 2) == []


async def test_upsert_then_search_finds_student(tmp_path: object) -> None:
    idx = _make(tmp_path)
    await idx.upsert("s1", "alice", [normalized([1.0])], {})
    res = await idx.search("s1", normalized([1.0]), 2)
    assert [c.student_id for c in res] == ["alice"]
    assert res[0].score == pytest.approx(1.0, abs=1e-5)


async def test_tenant_isolation(tmp_path: object) -> None:
    idx = _make(tmp_path)
    await idx.upsert("s1", "alice", [normalized([1.0])], {})
    await idx.upsert("s2", "bob", [normalized([1.0])], {})
    res = await idx.search("s2", normalized([1.0]), 5)
    assert [c.student_id for c in res] == ["bob"]  # never sees s1's alice


async def test_replace_not_append(tmp_path: object) -> None:
    idx = _make(tmp_path)
    await idx.upsert("s1", "alice", [normalized([1.0])], {})
    await idx.upsert("s1", "alice", [normalized([0.0, 1.0])], {})  # replaces
    old = await idx.search("s1", normalized([1.0]), 5)
    assert old[0].score == pytest.approx(0.0, abs=1e-5)  # old direction gone
    new = await idx.search("s1", normalized([0.0, 1.0]), 5)
    assert new[0].student_id == "alice"
    assert new[0].score == pytest.approx(1.0, abs=1e-5)


async def test_multi_vector_collapses_to_one_per_student(tmp_path: object) -> None:
    idx = _make(tmp_path)
    await idx.upsert("s1", "alice", [normalized([1.0]), normalized([0.0, 1.0])], {})
    res = await idx.search("s1", normalized([1.0]), 2)
    assert [c.student_id for c in res] == ["alice"]  # one row despite two vectors


async def test_search_respects_top_k(tmp_path: object) -> None:
    idx = _make(tmp_path)
    await idx.upsert("s1", "a", [normalized([1.0])], {})
    await idx.upsert("s1", "b", [normalized([0.9, 0.1])], {})
    await idx.upsert("s1", "c", [normalized([0.8, 0.2])], {})
    res = await idx.search("s1", normalized([1.0]), 2)
    assert len(res) == 2
    assert res[0].score >= res[1].score  # sorted descending


async def test_delete_removes_student(tmp_path: object) -> None:
    idx = _make(tmp_path)
    await idx.upsert("s1", "alice", [normalized([1.0])], {})
    await idx.delete("s1", "alice")
    assert await idx.search("s1", normalized([1.0]), 2) == []


async def test_delete_unknown_student_is_noop(tmp_path: object) -> None:
    idx = _make(tmp_path)
    await idx.upsert("s1", "alice", [normalized([1.0])], {})
    await idx.delete("s1", "ghost")  # not present
    res = await idx.search("s1", normalized([1.0]), 2)
    assert [c.student_id for c in res] == ["alice"]


async def test_version_mismatch_fails_loud(tmp_path: object) -> None:
    store = LocalFsIndexStore(str(tmp_path))
    writer = FaissPerSchoolVectorIndex(store, "old-embedder")
    await writer.upsert("s1", "alice", [normalized([1.0])], {})
    reader = FaissPerSchoolVectorIndex(store, "new-embedder")  # different model
    with pytest.raises(EmbeddingVersionMismatch):
        await reader.search("s1", normalized([1.0]), 2)


async def test_reload_after_write_sees_new_student(tmp_path: object) -> None:
    idx = _make(tmp_path)
    await idx.upsert("s1", "alice", [normalized([1.0])], {})
    await idx.search("s1", normalized([1.0]), 2)  # warms the cache
    await idx.upsert("s1", "bob", [normalized([0.0, 1.0])], {})  # bumps version
    res = await idx.search("s1", normalized([0.0, 1.0]), 5)
    assert any(c.student_id == "bob" for c in res)  # reloaded, not stale
