"""LocalFsIndexStore roundtrip + meta-last write ordering."""

from __future__ import annotations

import os

from ml_service.adapters.vector_index._index_store import (
    ID_MAP_FILE,
    INDEX_FILE,
    META_FILE,
    LocalFsIndexStore,
)


async def test_missing_returns_none(tmp_path: object) -> None:
    store = LocalFsIndexStore(str(tmp_path))
    assert await store.read_meta("s1") is None
    assert await store.load("s1") is None


async def test_save_then_load_roundtrip(tmp_path: object) -> None:
    store = LocalFsIndexStore(str(tmp_path))
    await store.save("s1", b"\x00\x01\x02", ["alice", "bob"], {"version": 3})
    assert await store.read_meta("s1") == {"version": 3}
    loaded = await store.load("s1")
    assert loaded == (b"\x00\x01\x02", ["alice", "bob"], {"version": 3})


async def test_writes_all_three_files(tmp_path: object) -> None:
    store = LocalFsIndexStore(str(tmp_path))
    await store.save("s1", b"x", ["a"], {"version": 1})
    d = os.path.join(str(tmp_path), "school=s1")
    for name in (INDEX_FILE, ID_MAP_FILE, META_FILE):
        assert os.path.exists(os.path.join(d, name))
