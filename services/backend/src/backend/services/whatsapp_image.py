"""Build a smaller, WhatsApp-sized image variant from a stored object (W1 + W2).

Pure orchestration over the ``ObjectStore`` + ``Thumbnailer`` ports — no image library, no
HTTP (layering-safe). Downloads the stored original and re-encodes it to a smaller JPEG within
``max_edge``/``quality``, reusing the BP17 thumbnailer's per-call override.

W2 ENFORCES the ≤5 MB WhatsApp byte ceiling: if the first re-encode still exceeds ``max_bytes``,
step the JPEG quality down toward ``quality_floor``, then (if still over) step the longest edge
down, returning the first result at or under the cap. If nothing gets under the cap — or the
source is a non-image / a decode error / a store outage — return ``None`` (best-effort; a bad or
un-shrinkable image never blocks the rest of the send batch, and an over-cap variant is never
sent). W1's callers (which passed no ``max_bytes``) keep the pre-W2 behaviour: no byte check.
"""

from __future__ import annotations

from backend.domain.errors import UpstreamError
from backend.domain.ports import ObjectStore, Thumbnailer

# Longest-edge fallbacks tried (largest → smallest) when the quality floor alone won't fit under
# the byte cap. Bounded + deterministic; a value at/above ``max_edge`` is skipped.
_EDGE_STEPS = (2000, 1600, 1200, 800)
# Quality step-down decrement when re-encoding to get under the byte cap.
_QUALITY_STEP = 10


async def make_whatsapp_variant(
    object_store: ObjectStore,
    thumbnailer: Thumbnailer,
    source_path: str,
    *,
    max_edge: int,
    quality: int,
    max_bytes: int | None = None,
    quality_floor: int = 40,
) -> bytes | None:
    """Return WhatsApp-ready JPEG bytes for the stored object at ``source_path``, or ``None``
    if it can't be produced within the (optional) ``max_bytes`` ceiling — best-effort.

    ``max_bytes=None`` (W1) → the first re-encode is returned with no byte check. ``max_bytes``
    set (W2) → step quality down (to ``quality_floor``), then edge down, returning the first
    variant at or under the cap; ``None`` if none fits."""
    try:
        data = await object_store.download_bytes(source_path)
    except UpstreamError:
        return None

    first = await thumbnailer.make_thumbnail(data, max_edge=max_edge, quality=quality)
    if first is None:
        return None  # non-image / decode/encode failure
    if max_bytes is None or len(first) <= max_bytes:
        return first

    # Over the cap: step the quality down at the original edge first (cheaper — keeps resolution).
    q = quality - _QUALITY_STEP
    while q >= quality_floor:
        candidate = await thumbnailer.make_thumbnail(
            data, max_edge=max_edge, quality=q
        )
        if candidate is not None and len(candidate) <= max_bytes:
            return candidate
        q -= _QUALITY_STEP

    # Still over at the quality floor: shrink the longest edge (at the floor quality) too.
    for edge in _EDGE_STEPS:
        if edge >= max_edge:
            continue  # only ever go smaller than the requested edge
        candidate = await thumbnailer.make_thumbnail(
            data, max_edge=edge, quality=quality_floor
        )
        if candidate is not None and len(candidate) <= max_bytes:
            return candidate

    return None  # un-shrinkable under the cap — never send an over-cap image
