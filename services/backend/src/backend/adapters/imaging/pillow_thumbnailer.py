"""Pillow ``Thumbnailer`` — downscale an image to a small JPEG preview (BP17, decisions/0056).

The ONLY module that decodes image bytes in the backend. Kept behind the ``Thumbnailer`` port
so ``domain``/``services`` never import an image library (the layering invariant). Best-effort:
any decode/encode failure (a non-image, a truncated/corrupt file, an unsupported mode) returns
``None`` so a bad image never fails the upload — display then falls back to the full-res object.
"""

from __future__ import annotations

import io

import anyio


class PillowThumbnailer:
    """Resize the longest edge to ``max_edge`` and re-encode as a JPEG at ``quality``."""

    def __init__(self, *, max_edge: int, quality: int) -> None:
        self._max_edge = max_edge
        self._quality = quality

    async def make_thumbnail(
        self, data: bytes, *, max_edge: int | None = None, quality: int | None = None
    ) -> bytes | None:
        # Pillow is CPU-bound and synchronous — offload so the event loop isn't blocked
        # (mirrors SupabaseObjectStore's anyio.to_thread pattern). W1: an optional per-call
        # size/quality override (else the instance config) for the WhatsApp variant.
        edge = max_edge if max_edge is not None else self._max_edge
        qual = quality if quality is not None else self._quality
        return await anyio.to_thread.run_sync(self._make_sync, data, edge, qual)

    def _make_sync(self, data: bytes, max_edge: int, quality: int) -> bytes | None:
        from PIL import Image, ImageOps

        try:
            with Image.open(io.BytesIO(data)) as opened:
                # Honour EXIF orientation, then flatten to RGB (JPEG has no alpha) so PNGs /
                # rotated phone photos thumbnail correctly.
                oriented = ImageOps.exif_transpose(opened) or opened
                rgb = oriented if oriented.mode == "RGB" else oriented.convert("RGB")
                # thumbnail() preserves aspect ratio and never upscales (mutates in place).
                rgb.thumbnail((max_edge, max_edge))
                out = io.BytesIO()
                rgb.save(out, format="JPEG", quality=quality)
                return out.getvalue()
        except Exception:  # noqa: BLE001 — best-effort; a bad image must never fail the upload
            return None
