"""Build a smaller, WhatsApp-sized image variant from a stored object (W1).

Pure orchestration over the ``ObjectStore`` + ``Thumbnailer`` ports — no image library, no
HTTP (layering-safe). Downloads the stored original and re-encodes it to a smaller JPEG within
``max_edge``/``quality``, reusing the BP17 thumbnailer's per-call override. NOTE: this only
resizes + re-encodes — it does NOT measure output bytes, so it is NOT a hard ≤5 MB cap; a dense
image can still exceed WhatsApp's 5 MB limit. The loop-down-quality-until-under-5 MB refinement
is deferred to W2 (the send path), which must enforce the byte ceiling before sending.
Best-effort: a non-image / decode failure / store outage returns ``None`` (the caller falls
back — a bad image never blocks a send). W1 builds this but calls it from nothing yet (W2 sends).
"""

from __future__ import annotations

from backend.domain.errors import UpstreamError
from backend.domain.ports import ObjectStore, Thumbnailer


async def make_whatsapp_variant(
    object_store: ObjectStore,
    thumbnailer: Thumbnailer,
    source_path: str,
    *,
    max_edge: int,
    quality: int,
) -> bytes | None:
    """Return WhatsApp-ready JPEG bytes for the stored object at ``source_path``, or ``None``
    if it can't be produced (a non-image / decode error / store outage) — best-effort."""
    try:
        data = await object_store.download_bytes(source_path)
    except UpstreamError:
        return None
    return await thumbnailer.make_thumbnail(data, max_edge=max_edge, quality=quality)
