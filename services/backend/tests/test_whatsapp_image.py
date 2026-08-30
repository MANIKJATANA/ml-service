"""The WhatsApp image variant helper (W1).

Pure orchestration over the ObjectStore + Thumbnailer ports: download the original, re-encode
to the WhatsApp size. Bytes for an image; None for a non-image / a failed compress / a store
outage (best-effort). W1 builds this but calls it from nothing (the send path is W2).
"""

from __future__ import annotations

from collections.abc import Callable

from backend.services.whatsapp_image import make_whatsapp_variant
from backend_fakes import FakeObjectStore, FakeThumbnailer


async def test_returns_bytes_for_an_image() -> None:
    store = FakeObjectStore()
    thumbnailer = FakeThumbnailer()  # produces fixed bytes
    out = await make_whatsapp_variant(
        store, thumbnailer, "events/s1/e1/m1", max_edge=2000, quality=80
    )
    assert out == b"thumb-bytes"
    # The per-call override was passed through (distinct from the BP17 instance defaults).
    assert thumbnailer.last_override == (2000, 80)


async def test_returns_none_for_a_non_image_or_failed_compress() -> None:
    store = FakeObjectStore()
    thumbnailer = FakeThumbnailer(produces=False)  # simulates a non-image / decode failure
    out = await make_whatsapp_variant(
        store, thumbnailer, "events/s1/e1/notes.txt", max_edge=2000, quality=80
    )
    assert out is None


async def test_returns_none_on_store_outage() -> None:
    store = FakeObjectStore(fail_downloads=True)  # download raises UpstreamError
    thumbnailer = FakeThumbnailer()
    out = await make_whatsapp_variant(
        store, thumbnailer, "events/s1/e1/m1", max_edge=2000, quality=80
    )
    assert out is None
    assert thumbnailer.calls == 0  # never reached the compressor


# ---- W2: the ≤5 MB byte cap (max_bytes) --------------------------------


class _SizedThumbnailer:
    """A thumbnailer whose output byte-length depends on the per-call quality/edge — so the
    W2 step-down + un-shrinkable paths are exercised. ``size_for(q, edge)`` returns a length;
    ``produces=False`` → always None (non-image)."""

    def __init__(
        self,
        *,
        size_for: Callable[[int | None, int | None], int],
        produces: bool = True,
    ) -> None:
        self._size_for = size_for
        self._produces = produces
        self.calls: list[tuple[int | None, int | None]] = []

    async def make_thumbnail(
        self, data: bytes, *, max_edge: int | None = None, quality: int | None = None
    ) -> bytes | None:
        self.calls.append((max_edge, quality))
        if not self._produces:
            return None
        return b"x" * self._size_for(quality, max_edge)


async def test_first_pass_over_cap_steps_quality_down_to_under_cap() -> None:
    store = FakeObjectStore()
    # At quality 80 it's over the 100-byte cap; each -10 step halves the size; by q=60 it fits.
    def size_for(q: int | None, _edge: int | None) -> int:
        if q is None:
            q = 80
        return {80: 200, 70: 150, 60: 90}.get(q, 90)

    thumbnailer = _SizedThumbnailer(size_for=size_for)
    out = await make_whatsapp_variant(
        store,
        thumbnailer,
        "events/s1/e1/m1",
        max_edge=2000,
        quality=80,
        max_bytes=100,
        quality_floor=40,
    )
    assert out is not None and len(out) <= 100
    # The first (over-cap) pass + step-downs were attempted at the SAME edge until it fit.
    assert thumbnailer.calls[0] == (2000, 80)
    assert (2000, 60) in thumbnailer.calls


async def test_unshrinkable_returns_none() -> None:
    store = FakeObjectStore()
    # Never under the cap at any quality/edge → None (never send an over-cap image).
    thumbnailer = _SizedThumbnailer(size_for=lambda q, edge: 10_000)
    out = await make_whatsapp_variant(
        store,
        thumbnailer,
        "events/s1/e1/m1",
        max_edge=2000,
        quality=80,
        max_bytes=100,
        quality_floor=40,
    )
    assert out is None
    # It tried quality step-downs AND smaller edges before giving up.
    assert any(edge is not None and edge < 2000 for edge, _q in thumbnailer.calls)


async def test_non_image_with_cap_returns_none() -> None:
    store = FakeObjectStore()
    thumbnailer = _SizedThumbnailer(size_for=lambda q, edge: 10, produces=False)
    out = await make_whatsapp_variant(
        store,
        thumbnailer,
        "events/s1/e1/notes.txt",
        max_edge=2000,
        quality=80,
        max_bytes=100,
    )
    assert out is None


async def test_store_outage_with_cap_returns_none() -> None:
    store = FakeObjectStore(fail_downloads=True)
    thumbnailer = _SizedThumbnailer(size_for=lambda q, edge: 10)
    out = await make_whatsapp_variant(
        store, thumbnailer, "events/s1/e1/m1", max_edge=2000, quality=80, max_bytes=100
    )
    assert out is None
    assert thumbnailer.calls == []


async def test_first_pass_under_cap_returns_immediately() -> None:
    store = FakeObjectStore()
    thumbnailer = _SizedThumbnailer(size_for=lambda q, edge: 50)  # already under 100
    out = await make_whatsapp_variant(
        store, thumbnailer, "events/s1/e1/m1", max_edge=2000, quality=80, max_bytes=100
    )
    assert out is not None
    assert len(thumbnailer.calls) == 1  # no step-down needed
