"""LocalFsObjectStore: deterministic file:// upload + download URLs (0026, 0028).

The credential-free dev stub — no real signing. The supabase adapter's signing path
needs a live client and is exercised in integration, not here.
"""

from __future__ import annotations

from backend.adapters.object_store.local_fs_store import LocalFsObjectStore


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
