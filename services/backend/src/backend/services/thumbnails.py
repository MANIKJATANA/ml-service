"""Backend image-thumbnail generation (BP17, decisions/0056).

Pure orchestration over the ``ObjectStore`` + ``Thumbnailer`` ports (no image library — Pillow
lives in the adapter, so layering holds). After the frontend uploads an original image, the
backend downloads it, compresses it, and uploads a small JPEG sibling, returning its object key
to persist. The thumbnail is display-only; the ML pipeline always reads the full-res original.
"""

from __future__ import annotations

from pathlib import PurePosixPath

import structlog

from backend.domain.ports import ObjectStore, Thumbnailer

_log = structlog.get_logger(__name__)


def thumb_key(primary_path: str) -> str:
    """Derive the thumbnail object key for an original — ``{dir}/thumb-{name}.jpg``.

    Stays under the original's tenant/event prefix (so it passes the existing register/create
    path guards). A leading ``thumb-`` marker + a real ``.jpg`` extension — deliberately NOT a
    ``.thumb`` suffix, which Supabase mishandles (an unknown extension breaks the upload).

    Assumes the extension-less object keys the two ``create_upload_url`` mints produce (a bare
    ``{uuid4}``): keying off ``stem`` then means ``{uuid}`` → ``thumb-{uuid}.jpg`` uniquely. (A
    hand-crafted dotted key could alias its own thumbnail — a self-inflicted, in-tenant no-op.)"""
    p = PurePosixPath(primary_path)
    return str(p.parent / f"thumb-{p.stem}.jpg")


async def generate_thumbnail(
    object_store: ObjectStore, thumbnailer: Thumbnailer, primary_path: str
) -> str | None:
    """Download the just-uploaded original, compress it, upload the thumbnail sibling, and
    return its key — or ``None`` if it couldn't be produced.

    Best-effort: any failure (an unreachable store, a non-image, a decode error) is logged and
    returns ``None`` so a missing thumbnail never fails the upload — display falls back to the
    full-res object. ``asyncio.CancelledError`` (a ``BaseException``) is not swallowed."""
    try:
        data = await object_store.download_bytes(primary_path)
        thumb = await thumbnailer.make_thumbnail(data)
        if thumb is None:
            return None
        key = thumb_key(primary_path)
        await object_store.upload_bytes(key, thumb, content_type="image/jpeg")
        return key
    except Exception:  # noqa: BLE001 — best-effort; a thumbnail must never fail the upload
        _log.warning(
            "thumbnail_generation_failed", primary_path=primary_path, exc_info=True
        )
        return None
