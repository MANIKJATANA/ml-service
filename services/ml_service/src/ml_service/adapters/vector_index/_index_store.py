"""Backing store for per-school FAISS index files (architecture §7.1).

Three objects per school — ``index.faiss`` (binary), ``id_map.json`` (row →
student_id), ``meta.json`` (``{embedding_model_version, dim, metric, version,
count}``). ``meta.json`` is written **last** and is the commit point: readers key
off ``meta.version`` (architecture §7.4).

Two implementations: ``LocalFsIndexStore`` (dev/tests, a shared Docker volume in
compose) and ``SupabaseIndexStore`` (Supabase Storage, prod). Both wrap their
blocking I/O in threads so the async ``VectorIndex`` stays non-blocking.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Protocol, cast

import anyio

INDEX_FILE = "index.faiss"
ID_MAP_FILE = "id_map.json"
META_FILE = "meta.json"

# A loaded triple: (serialized index bytes, row→student_id map, meta dict).
IndexBlob = tuple[bytes, list[str], dict[str, object]]


class IndexStore(Protocol):
    """Reads/writes a school's index triple. ``read_meta`` is the cheap staleness
    check the read path runs before deciding to reload (architecture §7.3)."""

    async def read_meta(self, school_id: str) -> dict[str, object] | None: ...

    async def load(self, school_id: str) -> IndexBlob | None: ...

    async def save(
        self,
        school_id: str,
        index_bytes: bytes,
        id_map: list[str],
        meta: dict[str, object],
    ) -> None: ...


def _atomic_write(path: str, data: bytes) -> None:
    """Write via a temp file + ``os.replace`` so readers never see a torn file."""
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


class LocalFsIndexStore:
    """Index files under ``{base_dir}/school={school_id}/``. Used for dev/tests
    and a shared Docker volume in compose."""

    def __init__(self, base_dir: str) -> None:
        self._base = base_dir

    def _dir(self, school_id: str) -> str:
        return os.path.join(self._base, f"school={school_id}")

    async def read_meta(self, school_id: str) -> dict[str, object] | None:
        return await anyio.to_thread.run_sync(self._read_meta_sync, school_id)

    def _read_meta_sync(self, school_id: str) -> dict[str, object] | None:
        path = os.path.join(self._dir(school_id), META_FILE)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return cast("dict[str, object]", json.load(f))

    async def load(self, school_id: str) -> IndexBlob | None:
        return await anyio.to_thread.run_sync(self._load_sync, school_id)

    def _load_sync(self, school_id: str) -> IndexBlob | None:
        d = self._dir(school_id)
        meta_path = os.path.join(d, META_FILE)
        index_path = os.path.join(d, INDEX_FILE)
        id_map_path = os.path.join(d, ID_MAP_FILE)
        if not os.path.exists(meta_path) or not os.path.exists(index_path):
            return None
        with open(index_path, "rb") as f:
            index_bytes = f.read()
        with open(id_map_path, encoding="utf-8") as f:
            id_map = cast("list[str]", json.load(f))
        with open(meta_path, encoding="utf-8") as f:
            meta = cast("dict[str, object]", json.load(f))
        return index_bytes, id_map, meta

    async def save(
        self,
        school_id: str,
        index_bytes: bytes,
        id_map: list[str],
        meta: dict[str, object],
    ) -> None:
        await anyio.to_thread.run_sync(
            self._save_sync, school_id, index_bytes, id_map, meta
        )

    def _save_sync(
        self,
        school_id: str,
        index_bytes: bytes,
        id_map: list[str],
        meta: dict[str, object],
    ) -> None:
        d = self._dir(school_id)
        os.makedirs(d, exist_ok=True)
        # index + id_map first, meta LAST — the commit point (architecture §7.4).
        _atomic_write(os.path.join(d, INDEX_FILE), index_bytes)
        _atomic_write(
            os.path.join(d, ID_MAP_FILE), json.dumps(id_map).encode("utf-8")
        )
        _atomic_write(os.path.join(d, META_FILE), json.dumps(meta).encode("utf-8"))


class SupabaseIndexStore:
    """Index files in a Supabase Storage bucket under
    ``{prefix}/school={school_id}/``. The access key is a secret injected by
    wiring (Phase 3) — never stored in code."""

    def __init__(
        self,
        url: str,
        key: str,
        bucket: str,
        *,
        prefix: str = "faiss-indexes",
    ) -> None:
        from supabase import create_client

        self._client = create_client(url, key)
        self._bucket = bucket
        self._prefix = prefix

    def _path(self, school_id: str, name: str) -> str:
        return f"{self._prefix}/school={school_id}/{name}"

    def _download(self, path: str) -> bytes | None:
        try:
            return bytes(self._client.storage.from_(self._bucket).download(path))
        except Exception:
            # storage3 raises on a missing object; treat as "not present".
            return None

    def _upload(self, path: str, data: bytes, content_type: str) -> None:
        self._client.storage.from_(self._bucket).upload(
            path,
            data,
            {"content-type": content_type, "upsert": "true"},
        )

    async def read_meta(self, school_id: str) -> dict[str, object] | None:
        raw = await anyio.to_thread.run_sync(
            self._download, self._path(school_id, META_FILE)
        )
        return None if raw is None else cast("dict[str, object]", json.loads(raw))

    async def load(self, school_id: str) -> IndexBlob | None:
        return await anyio.to_thread.run_sync(self._load_sync, school_id)

    def _load_sync(self, school_id: str) -> IndexBlob | None:
        meta_raw = self._download(self._path(school_id, META_FILE))
        index_bytes = self._download(self._path(school_id, INDEX_FILE))
        id_map_raw = self._download(self._path(school_id, ID_MAP_FILE))
        if meta_raw is None or index_bytes is None or id_map_raw is None:
            return None
        return (
            index_bytes,
            cast("list[str]", json.loads(id_map_raw)),
            cast("dict[str, object]", json.loads(meta_raw)),
        )

    async def save(
        self,
        school_id: str,
        index_bytes: bytes,
        id_map: list[str],
        meta: dict[str, object],
    ) -> None:
        await anyio.to_thread.run_sync(
            self._save_sync, school_id, index_bytes, id_map, meta
        )

    def _save_sync(
        self,
        school_id: str,
        index_bytes: bytes,
        id_map: list[str],
        meta: dict[str, object],
    ) -> None:
        # index + id_map first, meta LAST — the commit point (architecture §7.4).
        self._upload(
            self._path(school_id, INDEX_FILE), index_bytes, "application/octet-stream"
        )
        self._upload(
            self._path(school_id, ID_MAP_FILE),
            json.dumps(id_map).encode("utf-8"),
            "application/json",
        )
        self._upload(
            self._path(school_id, META_FILE),
            json.dumps(meta).encode("utf-8"),
            "application/json",
        )
