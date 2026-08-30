"""Local-filesystem ``ObjectStore`` — a credential-free dev stub (decisions/0026).

For offline/local dev (paired with the ``fake`` ML client) so the backend runs with
no Supabase. The signed-upload/-download flow does NOT accept real bytes: it returns a
deterministic ``file://`` target under ``object_store_dir`` so the create-student flow
and its path guard can be exercised end to end. Real signed uploads use the ``supabase``
impl.

The byte-level methods (``upload_bytes``/``download_bytes``/``delete``) and W3a's
``list_prefix`` DO operate on the real filesystem under ``base_dir``, so the store is
round-trippable in dev/tests (e.g. the WhatsApp-variant reaper lists + deletes objects).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from backend.domain.errors import UpstreamError
from backend.domain.models import SignedUpload, StoredObject


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
        # Remove the real file if one was written (upload_bytes). Idempotent — a missing
        # object is a no-op, mirroring the supabase impl's remove() (BP8e). The
        # signed-upload flow itself never writes bytes here, so for the create-student path
        # this stays effectively a no-op.
        target = self._file_for(object_path)
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:  # pragma: no cover - unexpected fs error
            raise UpstreamError(
                f"local_fs delete failed for {object_path!r}: {exc}"
            ) from exc

    async def download_bytes(self, object_path: str) -> bytes:
        # Return the real bytes if a file was written (upload_bytes); otherwise raise, as
        # before. The signed-upload flow writes nothing here, so BP17 thumbnail generation
        # stays a best-effort no-op locally (the service catches the raise → thumbnail_path=
        # None → display falls back to full-res). Real reads use the supabase impl (0056).
        target = self._file_for(object_path)
        try:
            return target.read_bytes()
        except FileNotFoundError as exc:
            raise UpstreamError(
                f"local_fs has no object at {object_path!r} "
                "(dev stub stores no bytes for the signed-upload flow)"
            ) from exc
        except OSError as exc:  # pragma: no cover - unexpected fs error
            raise UpstreamError(
                f"local_fs read failed for {object_path!r}: {exc}"
            ) from exc

    async def upload_bytes(
        self, object_path: str, data: bytes, *, content_type: str
    ) -> None:
        # Write real bytes under base_dir so the object store is round-trippable in dev/tests
        # (W3a: the reaper lists + deletes these). Overwrites, mirroring the supabase upsert.
        target = self._file_for(object_path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except OSError as exc:  # pragma: no cover - unexpected fs error
            raise UpstreamError(
                f"local_fs write failed for {object_path!r}: {exc}"
            ) from exc

    async def list_prefix(self, prefix: str) -> list[StoredObject]:
        # Walk base_dir/prefix recursively; each file → a StoredObject whose key is the
        # forward-slash path relative to base_dir and whose last_modified is the file mtime
        # as a tz-aware UTC datetime. A missing prefix dir → [] (nothing has been written).
        root = self._file_for(prefix)
        if not root.exists():
            return []
        out: list[StoredObject] = []
        try:
            for entry in root.rglob("*"):
                if not entry.is_file():
                    continue
                key = entry.relative_to(Path(self._base)).as_posix()
                mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=UTC)
                out.append(StoredObject(key=key, last_modified=mtime))
        except OSError as exc:  # pragma: no cover - unexpected fs error
            raise UpstreamError(
                f"local_fs list failed for {prefix!r}: {exc}"
            ) from exc
        return out

    def _file_for(self, object_path: str) -> Path:
        """Map an object key to its on-disk path under ``base_dir`` (leading slash stripped)."""
        return Path(self._base) / object_path.lstrip("/")
