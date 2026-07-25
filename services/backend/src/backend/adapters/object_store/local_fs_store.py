"""Local-filesystem ``ObjectStore`` — a credential-free dev stub (decisions/0026).

For offline/local dev (paired with the ``fake`` ML client) so the backend runs with
no Supabase. It does NOT actually accept an upload; it returns a deterministic
``file://`` target under ``object_store_dir`` so the create-student flow and its path
guard can be exercised end to end. Real uploads use the ``supabase`` impl.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from backend.domain.errors import UpstreamError
from backend.domain.models import SignedUpload


class LocalFsObjectStore:
    """Returns a ``file://`` upload target rooted at ``base_dir`` (no real upload)."""

    def __init__(self, base_dir: str) -> None:
        self._base = base_dir.rstrip("/")

    async def create_signed_upload_url(self, object_path: str) -> SignedUpload:
        path = object_path.lstrip("/")
        target = PurePosixPath(self._base) / path
        return SignedUpload(
            upload_url=f"file://{target}", object_path=path, token=None
        )

    async def create_signed_download_url(
        self, object_path: str, *, expires_in_s: int
    ) -> str:
        # Dev stub: a deterministic file:// URL (no real signing / expiry), mirroring
        # the upload stub (decisions/0028). Real downloads use the supabase impl.
        target = PurePosixPath(self._base) / object_path.lstrip("/")
        return f"file://{target}"

    async def delete(self, object_path: str) -> None:
        # Dev stub: uploads aren't real here (no bytes are ever written), so there's
        # nothing to remove — a no-op. Real deletes use the supabase impl (BP8e).
        return None

    async def download_bytes(self, object_path: str) -> bytes:
        # Dev stub: no real bytes were ever uploaded here, so there's nothing to read.
        # Raising makes BP17 thumbnail generation a best-effort no-op locally (the service
        # catches it → thumbnail_path=None → display falls back to full-res). Real reads use
        # the supabase impl (decisions/0056).
        raise UpstreamError(
            "local_fs dev stub stores no bytes; thumbnails need the supabase impl"
        )

    async def upload_bytes(
        self, object_path: str, data: bytes, *, content_type: str
    ) -> None:
        # Dev stub: no-op (mirrors the no-op upload/delete). Real writes use the supabase impl.
        return None
