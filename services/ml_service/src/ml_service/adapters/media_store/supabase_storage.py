"""Supabase Storage ``MediaStore`` — the default media source (decisions/0010).

Handles both storage object paths (downloaded via the Supabase client) and full
``http(s)`` URLs (fetched with httpx) — the backend may record either form. The
access key is a secret injected by wiring (Phase 3); it is never stored in code.
"""

from __future__ import annotations

import anyio

from ml_service.domain.errors import MediaFetchError


class SupabaseMediaStore:
    """Fetches media bytes from a Supabase Storage bucket (or an http URL)."""

    def __init__(self, url: str, key: str, bucket: str) -> None:
        from supabase import create_client

        self._client = create_client(url, key)
        self._bucket = bucket

    async def fetch(self, media_uri: str) -> bytes:
        return await anyio.to_thread.run_sync(self._fetch_sync, media_uri)

    async def upload(self, object_path: str, data: bytes, content_type: str) -> str:
        """Upload bytes to the bucket (upsert) and return the bucket-relative path.

        Not part of the ``MediaStore`` port — a convenience used by the dev test
        UI (decisions/0019) so a browser-uploaded photo lands in Supabase before
        enrollment fetches it back. Returns a URI ``fetch`` can round-trip.
        """
        path = self._object_path(object_path)
        await anyio.to_thread.run_sync(self._upload_sync, path, data, content_type)
        return path

    def _upload_sync(self, path: str, data: bytes, content_type: str) -> None:
        try:
            self._client.storage.from_(self._bucket).upload(
                path=path,
                file=data,
                file_options={"content-type": content_type, "upsert": "true"},
            )
        except Exception as exc:  # storage3 raises on transport/permission errors
            raise MediaFetchError(
                f"supabase upload failed for {path!r}: {exc}"
            ) from exc

    def _fetch_sync(self, media_uri: str) -> bytes:
        if media_uri.startswith(("http://", "https://")):
            return self._fetch_http(media_uri)
        path = self._object_path(media_uri)
        try:
            return bytes(self._client.storage.from_(self._bucket).download(path))
        except Exception as exc:  # storage3 raises on missing/forbidden objects
            raise MediaFetchError(
                f"supabase download failed for {media_uri!r}: {exc}"
            ) from exc

    def _fetch_http(self, url: str) -> bytes:
        import httpx

        try:
            resp = httpx.get(url, timeout=30.0, follow_redirects=True)
            resp.raise_for_status()
            return resp.content
        except httpx.HTTPError as exc:
            raise MediaFetchError(f"http fetch failed for {url!r}: {exc}") from exc

    def _object_path(self, media_uri: str) -> str:
        """Normalize to a bucket-relative object path, tolerating a leading
        ``{bucket}/`` prefix if the caller included it."""
        path = media_uri.lstrip("/")
        prefix = f"{self._bucket}/"
        if path.startswith(prefix):
            path = path[len(prefix) :]
        return path
