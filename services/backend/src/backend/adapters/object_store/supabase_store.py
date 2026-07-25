"""Supabase Storage ``ObjectStore`` — mints signed upload URLs (decisions/0026).

The backend never handles the reference-photo bytes: it signs a short-lived
direct-to-Supabase upload target for a caller-chosen object key; the frontend uploads
there and later submits the object path, which the ML service fetches from the SAME
bucket (``BE_SUPABASE_BUCKET`` must equal ``ML_SUPABASE_BUCKET``). The access key is a
secret injected by wiring; it is never stored in code.
"""

from __future__ import annotations

from typing import Any

import anyio

from backend.domain.errors import UpstreamError
from backend.domain.models import SignedUpload


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
