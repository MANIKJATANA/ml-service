"""W3a: the WhatsApp send-variant reaper (services/whatsapp_variant_reaper.py).

Fully covered by the FakeObjectStore (the local_fs adapter's list_prefix round-trip lives in
tests/test_object_store.py). A fixed ``now`` makes the age filter deterministic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from backend.services.whatsapp_variant_reaper import reap_whatsapp_variants
from backend_fakes import FakeObjectStore

_PREFIX = "whatsapp-variants"
_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
_RETENTION = timedelta(hours=24)


def _seed_ab(store: FakeObjectStore) -> None:
    """Seed schoolA + schoolB, each with one OLD (2 days) and one RECENT (1h) variant."""
    old = _NOW - timedelta(days=2)  # past the 24h retention
    recent = _NOW - timedelta(hours=1)  # inside retention
    store.put_object(f"{_PREFIX}/schoolA/media-old.jpg", modified=old)
    store.put_object(f"{_PREFIX}/schoolA/media-new.jpg", modified=recent)
    store.put_object(f"{_PREFIX}/schoolB/media-old.jpg", modified=old)
    store.put_object(f"{_PREFIX}/schoolB/media-new.jpg", modified=recent)


async def test_reaps_only_old_keeps_recent() -> None:
    store = FakeObjectStore()
    _seed_ab(store)

    summary = await reap_whatsapp_variants(
        store, prefix=_PREFIX, retention=_RETENTION, now=_NOW
    )

    assert summary.scanned == 4
    assert summary.deleted == 2
    assert summary.skipped_recent == 2
    assert summary.errors == 0
    # Exactly the two OLD objects were deleted; the recent ones survive.
    assert set(store.deleted) == {
        f"{_PREFIX}/schoolA/media-old.jpg",
        f"{_PREFIX}/schoolB/media-old.jpg",
    }
    assert set(store.uploaded) == {
        f"{_PREFIX}/schoolA/media-new.jpg",
        f"{_PREFIX}/schoolB/media-new.jpg",
    }


async def test_dry_run_deletes_nothing_but_reports() -> None:
    store = FakeObjectStore()
    _seed_ab(store)

    summary = await reap_whatsapp_variants(
        store, prefix=_PREFIX, retention=_RETENTION, now=_NOW, dry_run=True
    )

    assert summary.scanned == 4
    assert summary.deleted == 2  # what WOULD be deleted
    assert summary.skipped_recent == 2
    assert summary.errors == 0
    assert store.deleted == []  # nothing actually removed
    assert len(store.uploaded) == 4  # all objects intact


async def test_school_filter_touches_only_that_school() -> None:
    store = FakeObjectStore()
    _seed_ab(store)

    summary = await reap_whatsapp_variants(
        store, prefix=_PREFIX, retention=_RETENTION, now=_NOW, school_id="schoolA"
    )

    # Only schoolA's two objects are even scanned; only its old one is deleted.
    assert summary.scanned == 2
    assert summary.deleted == 1
    assert summary.skipped_recent == 1
    assert store.deleted == [f"{_PREFIX}/schoolA/media-old.jpg"]
    # schoolB is entirely untouched.
    assert f"{_PREFIX}/schoolB/media-old.jpg" in store.uploaded
    assert f"{_PREFIX}/schoolB/media-new.jpg" in store.uploaded


async def test_delete_failure_is_counted_and_run_continues() -> None:
    # schoolA's old delete raises; schoolB's old still gets reaped (best-effort).
    store = FakeObjectStore(fail_delete_keys={f"{_PREFIX}/schoolA/media-old.jpg"})
    _seed_ab(store)

    summary = await reap_whatsapp_variants(
        store, prefix=_PREFIX, retention=_RETENTION, now=_NOW
    )

    assert summary.scanned == 4
    assert summary.skipped_recent == 2
    assert summary.errors == 1  # schoolA's old delete failed
    assert summary.deleted == 1  # schoolB's old still deleted
    # Every scanned object lands in exactly one bucket — the counters can't silently drift.
    assert summary.deleted + summary.skipped_recent + summary.errors == summary.scanned
    assert store.deleted == [f"{_PREFIX}/schoolB/media-old.jpg"]
    # The failed object is NOT removed from the store (delete raised before recording).
    assert f"{_PREFIX}/schoolA/media-old.jpg" in store.uploaded


async def test_empty_prefix_is_a_clean_zero_summary() -> None:
    store = FakeObjectStore()  # nothing seeded

    summary = await reap_whatsapp_variants(
        store, prefix=_PREFIX, retention=_RETENTION, now=_NOW
    )

    assert summary.scanned == 0
    assert summary.deleted == 0
    assert summary.skipped_recent == 0
    assert summary.errors == 0
    assert store.deleted == []


async def test_object_at_exact_cutoff_is_reaped_not_kept() -> None:
    # last_modified == now - retention is NOT younger than the threshold, so it IS reaped
    # (the safety rule is "never delete an object YOUNGER than retention").
    store = FakeObjectStore()
    store.put_object(
        f"{_PREFIX}/schoolA/edge.jpg", modified=_NOW - _RETENTION
    )

    summary = await reap_whatsapp_variants(
        store, prefix=_PREFIX, retention=_RETENTION, now=_NOW
    )

    assert summary.deleted == 1
    assert summary.skipped_recent == 0
    assert store.deleted == [f"{_PREFIX}/schoolA/edge.jpg"]


async def test_non_positive_retention_is_refused() -> None:
    # Defense-in-depth: a <= 0 window would set the cutoff to now/the future and reap a fresh,
    # in-flight variant. The service refuses it (the CLI also guards it at argparse).
    store = FakeObjectStore()
    store.put_object(f"{_PREFIX}/schoolA/fresh.jpg", modified=_NOW)
    for bad in (timedelta(0), timedelta(hours=-1)):
        with pytest.raises(ValueError):
            await reap_whatsapp_variants(store, prefix=_PREFIX, retention=bad, now=_NOW)
    assert store.deleted == []  # nothing was touched


async def test_default_now_uses_wall_clock_and_keeps_a_fresh_upload() -> None:
    # No ``now`` passed → defaults to datetime.now(UTC); a just-uploaded (recent) object is
    # kept, proving the safety rule holds without an injected clock too.
    store = FakeObjectStore()
    store.set_clock(datetime.now(UTC))
    await store.upload_bytes(
        f"{_PREFIX}/schoolA/fresh.jpg", b"x", content_type="image/jpeg"
    )

    summary = await reap_whatsapp_variants(
        store, prefix=_PREFIX, retention=_RETENTION
    )

    assert summary.scanned == 1
    assert summary.deleted == 0
    assert summary.skipped_recent == 1
    assert store.deleted == []
