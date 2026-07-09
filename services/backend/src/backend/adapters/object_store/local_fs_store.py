"""Local-filesystem ``ObjectStore`` — a credential-free dev stub (decisions/0026).

For offline/local dev (paired with the ``fake`` ML client) so the backend runs with
no Supabase. It does NOT actually accept an upload; it returns a deterministic
``file://`` target under ``object_store_dir`` so the create-student flow and its path
guard can be exercised end to end. Real uploads use the ``supabase`` impl.
"""

from __future__ import annotations

from pathlib import PurePosixPath

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
