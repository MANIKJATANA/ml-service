"""LocalFsObjectStore: deterministic file:// upload + download URLs (0026, 0028) + the W3a
byte/list round-trip.

The signed upload/download flow is a credential-free dev stub — no real signing (the supabase
adapter's signing path needs a live client and is exercised in integration, not here). The
byte-level methods + ``list_prefix`` DO hit the real filesystem under ``base_dir``, so they're
covered here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from backend.adapters.object_store.local_fs_store import LocalFsObjectStore
from backend.domain.errors import UpstreamError


async def test_upload_url_is_rooted_and_strips_leading_slash() -> None:
    store = LocalFsObjectStore("/var/objs")
    signed = await store.create_signed_upload_url("/events/s1/e1/p.jpg")
    assert signed.upload_url == "file:///var/objs/events/s1/e1/p.jpg"
    assert signed.object_path == "events/s1/e1/p.jpg"
    assert signed.token is None


async def test_download_url_is_deterministic_and_root_normalised() -> None:
    # Trailing slash on the base is normalised away; leading slash on the key stripped.
    store = LocalFsObjectStore("/var/objs/")
    url = await store.create_signed_download_url(
        "/events/s1/e1/p.jpg", expires_in_s=60
    )
    assert url == "file:///var/objs/events/s1/e1/p.jpg"


# ---- W3a: byte round-trip + list_prefix -----------------------------------


async def test_list_prefix_round_trip(tmp_path: Path) -> None:
    store = LocalFsObjectStore(str(tmp_path))
    key_a = "whatsapp-variants/schoolA/media-1.jpg"
    key_b = "whatsapp-variants/schoolB/media-2.jpg"
    await store.upload_bytes(key_a, b"aaa", content_type="image/jpeg")
    await store.upload_bytes(key_b, b"bbb", content_type="image/jpeg")

    listed = await store.list_prefix("whatsapp-variants")

    assert {o.key for o in listed} == {key_a, key_b}  # recursive, two levels deep
    # Each carries a plausible tz-aware UTC last_modified near now.
    now = datetime.now(UTC)
    for obj in listed:
        assert obj.last_modified.tzinfo is not None
        assert now - obj.last_modified < timedelta(minutes=5)


async def test_list_prefix_missing_prefix_is_empty(tmp_path: Path) -> None:
    store = LocalFsObjectStore(str(tmp_path))
    assert await store.list_prefix("whatsapp-variants") == []


async def test_download_and_delete_round_trip(tmp_path: Path) -> None:
    store = LocalFsObjectStore(str(tmp_path))
    key = "whatsapp-variants/schoolA/media-1.jpg"
    await store.upload_bytes(key, b"payload", content_type="image/jpeg")

    assert await store.download_bytes(key) == b"payload"

    await store.delete(key)
    assert await store.list_prefix("whatsapp-variants") == []
    # delete is idempotent — a second delete of a now-missing key is a no-op.
    await store.delete(key)
    # download of a missing key raises (BP17 best-effort no-op locally).
    with pytest.raises(UpstreamError):
        await store.download_bytes(key)
