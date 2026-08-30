"""Supabase Storage ``ObjectStore`` — mints signed upload URLs (decisions/0026).

The backend never handles the reference-photo bytes: it signs a short-lived
direct-to-Supabase upload target for a caller-chosen object key; the frontend uploads
there and later submits the object path, which the ML service fetches from the SAME
bucket (``BE_SUPABASE_BUCKET`` must equal ``ML_SUPABASE_BUCKET``). The access key is a
secret injected by wiring; it is never stored in code.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import anyio

from backend.domain.errors import UpstreamError
from backend.domain.models import SignedUpload, StoredObject


class SupabaseObjectStore:
    """Signs uploads to a Supabase Storage bucket via storage3."""

    def __init__(self, url: str, key: str, bucket: str) -> None:
        from supabase import create_client

        self._client = create_client(url, key)
        self._bucket = bucket

    async def create_signed_upload_url(self, object_path: str) -> SignedUpload:
        return await anyio.to_thread.run_sync(self._sign_sync, object_path)

    async def create_signed_download_url(
        self, object_path: str, *, expires_in_s: int
    ) -> str:
        return await anyio.to_thread.run_sync(
            self._sign_download_sync, object_path, expires_in_s
        )

    async def delete(self, object_path: str) -> None:
        await anyio.to_thread.run_sync(self._delete_sync, object_path)

    async def download_bytes(self, object_path: str) -> bytes:
        return await anyio.to_thread.run_sync(self._download_bytes_sync, object_path)

    async def upload_bytes(
        self, object_path: str, data: bytes, *, content_type: str
    ) -> None:
        await anyio.to_thread.run_sync(
            self._upload_bytes_sync, object_path, data, content_type
        )

    async def list_prefix(self, prefix: str) -> list[StoredObject]:
        return await anyio.to_thread.run_sync(self._list_prefix_sync, prefix)

    def _list_prefix_sync(self, prefix: str) -> list[StoredObject]:
        # W3a. NOTE: this path is NOT unit-tested (it needs a live Supabase); it is exercised
        # only in the gated/live integration path, mirroring how the other supabase methods
        # (sign/upload/download/delete) are handled here. Supabase's storage .list(path) is
        # per-FOLDER (non-recursive), so to enumerate keys shaped
        # {prefix}/{school_id}/{media_id}.jpg we list the prefix folder to get the school
        # subfolders, then list each school folder to get its files, reading each file's
        # timestamp from the entry metadata. A missing/empty prefix → [].
        base = prefix.strip("/")
        bucket = self._client.storage.from_(self._bucket)
        out: list[StoredObject] = []
        try:
            schools = bucket.list(base)
        except Exception as exc:  # storage3 raises on transport/permission errors
            raise UpstreamError(
                f"supabase list failed for {base!r}: {exc}"
            ) from exc
        for school in schools or []:
            school_name = _entry_name(school)
            if not school_name:
                continue
            # A folder entry has no id/metadata; a stray file directly under the prefix has.
            # Only descend into folders (the {school_id} level); skip anything that is itself
            # a file (there shouldn't be one, but be tolerant).
            if _entry_is_file(school):
                out.append(
                    StoredObject(
                        key=f"{base}/{school_name}",
                        last_modified=_entry_modified(school),
                    )
                )
                continue
            folder = f"{base}/{school_name}"
            try:
                files = bucket.list(folder)
            except Exception as exc:  # storage3 raises on transport/permission errors
                raise UpstreamError(
                    f"supabase list failed for {folder!r}: {exc}"
                ) from exc
            for entry in files or []:
                name = _entry_name(entry)
                if not name or not _entry_is_file(entry):
                    continue
                out.append(
                    StoredObject(
                        key=f"{folder}/{name}",
                        last_modified=_entry_modified(entry),
                    )
                )
        return out

    def _download_bytes_sync(self, object_path: str) -> bytes:
        path = object_path.lstrip("/")
        try:
            return self._client.storage.from_(self._bucket).download(path)
        except Exception as exc:  # storage3 raises on missing/transport/permission errors
            raise UpstreamError(
                f"supabase download failed for {path!r}: {exc}"
            ) from exc

    def _upload_bytes_sync(
        self, object_path: str, data: bytes, content_type: str
    ) -> None:
        path = object_path.lstrip("/")
        try:
            # upsert so a re-run (e.g. a photo replace) overwrites rather than 409s.
            self._client.storage.from_(self._bucket).upload(
                path, data, {"content-type": content_type, "upsert": "true"}
            )
        except Exception as exc:  # storage3 raises on transport/permission errors
            raise UpstreamError(
                f"supabase upload failed for {path!r}: {exc}"
            ) from exc

    def _delete_sync(self, object_path: str) -> None:
        path = object_path.lstrip("/")
        try:
            # remove() is idempotent — removing a missing key is a no-op, not an error.
            self._client.storage.from_(self._bucket).remove([path])
        except Exception as exc:  # storage3 raises on transport/permission errors
            raise UpstreamError(
                f"supabase delete failed for {path!r}: {exc}"
            ) from exc

    def _sign_download_sync(self, object_path: str, expires_in_s: int) -> str:
        path = object_path.lstrip("/")
        try:
            res: Any = self._client.storage.from_(self._bucket).create_signed_url(
                path, expires_in_s
            )
        except Exception as exc:  # storage3 raises on transport/permission errors
            raise UpstreamError(
                f"supabase signed-download-url failed for {path!r}: {exc}"
            ) from exc
        url = _pick(res, "signed_url", "signedURL", "signedUrl")
        if not url:
            raise UpstreamError(
                f"supabase returned no signed url for {path!r}: {res!r}"
            )
        return url

    def _sign_sync(self, object_path: str) -> SignedUpload:
        path = object_path.lstrip("/")
        try:
            res: Any = self._client.storage.from_(self._bucket).create_signed_upload_url(
                path
            )
        except Exception as exc:  # storage3 raises on transport/permission errors
            raise UpstreamError(
                f"supabase signed-upload-url failed for {path!r}: {exc}"
            ) from exc
        # storage3 returns a mapping with signed_url/token/path (key spelling has
        # varied across versions) — read tolerantly and fail loud if absent.
        url = _pick(res, "signed_url", "signedURL", "signedUrl")
        token = _pick(res, "token")
        if not url:
            raise UpstreamError(
                f"supabase returned no signed url for {path!r}: {res!r}"
            )
        return SignedUpload(upload_url=url, object_path=path, token=token)


def _pick(res: Any, *keys: str) -> str | None:
    for key in keys:
        if isinstance(res, dict):
            value = res.get(key)
        else:
            value = getattr(res, key, None)
        if isinstance(value, str) and value:
            return value
    return None


def _entry_get(entry: Any, key: str) -> Any:
    """Read ``key`` from a storage list entry (a dict or an object), tolerantly."""
    if isinstance(entry, dict):
        return entry.get(key)
    return getattr(entry, key, None)


def _entry_name(entry: Any) -> str | None:
    name = _entry_get(entry, "name")
    return name if isinstance(name, str) and name else None


def _entry_is_file(entry: Any) -> bool:
    """A Supabase storage list entry is a FILE (not a subfolder) when it carries an ``id`` /
    ``metadata`` (folders come back with those null). Prefer ``metadata`` (has the size), fall
    back to ``id``."""
    metadata = _entry_get(entry, "metadata")
    if metadata:
        return True
    return _entry_get(entry, "id") is not None


def _entry_modified(entry: Any) -> datetime:
    """The object's last-modified time from a storage list entry — prefer ``updated_at``, then
    ``created_at``, then ``metadata.lastModified`` (spellings have varied across client
    versions). Falls back to ``now(UTC)`` (treated as "recent", so the age filter keeps it — a
    conservative default that never reaps an object whose timestamp we couldn't read)."""
    for key in ("updated_at", "created_at"):
        parsed = _parse_ts(_entry_get(entry, key))
        if parsed is not None:
            return parsed
    metadata = _entry_get(entry, "metadata")
    if metadata is not None:
        parsed = _parse_ts(_entry_get(metadata, "lastModified"))
        if parsed is not None:
            return parsed
    return datetime.now(UTC)


def _parse_ts(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp string (or a pre-parsed datetime) to a tz-aware UTC
    datetime; ``None`` when it can't be parsed."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            # Supabase returns e.g. "2026-08-30T12:34:56.789Z"; normalise the trailing Z.
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    return None
