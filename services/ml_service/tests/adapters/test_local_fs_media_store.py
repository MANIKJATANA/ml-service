"""LocalFsMediaStore fetch behaviour."""

from __future__ import annotations

import pathlib

import pytest
from ml_service.adapters.media_store.local_fs import LocalFsMediaStore
from ml_service.domain.errors import MediaFetchError


async def test_fetch_relative_path(tmp_path: pathlib.Path) -> None:
    (tmp_path / "a.jpg").write_bytes(b"payload")
    store = LocalFsMediaStore(str(tmp_path))
    assert await store.fetch("a.jpg") == b"payload"


async def test_missing_file_raises(tmp_path: pathlib.Path) -> None:
    store = LocalFsMediaStore(str(tmp_path))
    with pytest.raises(MediaFetchError):
        await store.fetch("nope.jpg")


async def test_file_uri(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "b.jpg"
    p.write_bytes(b"xy")
    store = LocalFsMediaStore(str(tmp_path))
    assert await store.fetch(p.as_uri()) == b"xy"
