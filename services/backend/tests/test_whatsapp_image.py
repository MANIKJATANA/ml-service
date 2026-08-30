"""The WhatsApp image variant helper (W1).

Pure orchestration over the ObjectStore + Thumbnailer ports: download the original, re-encode
to the WhatsApp size. Bytes for an image; None for a non-image / a failed compress / a store
outage (best-effort). W1 builds this but calls it from nothing (the send path is W2).
"""

from __future__ import annotations

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
