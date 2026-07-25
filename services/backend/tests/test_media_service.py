"""MediaService use-cases with fakes (decisions/0027).

Registering a photo only records it — processing is event-level (see
test_event_service.py's process_event tests). So there is no enqueue here.
"""

from __future__ import annotations

import pytest
from backend.domain.errors import NotFoundError, ValidationError
from backend.domain.models import (
    Event,
    EventStatus,
    Media,
    MediaProcessingStatus,
    MediaType,
)
from backend.services.media_service import MediaService
from backend_fakes import (
    FakeEventRepo,
    FakeMediaRepo,
    FakeObjectStore,
    FakeThumbnailer,
    make_event,
    make_media,
)

_S1 = "s1"
_E1 = "e1"
_PATH = "events/s1/e1/photo.jpg"


def _svc(
    *, events: list[Event] | None = None, media: list[Media] | None = None
) -> tuple[MediaService, FakeMediaRepo]:
    erepo = FakeEventRepo(
        events if events is not None else [make_event(id=_E1, school_id=_S1)]
    )
    mrepo = FakeMediaRepo(media or [])
    svc = MediaService(
        mrepo, erepo, FakeObjectStore(), FakeThumbnailer(), event_media_prefix="events"
    )
    return svc, mrepo


# ---- upload url --------------------------------------------------------


async def test_upload_url_is_under_event_prefix() -> None:
    svc, _ = _svc()
    # BP17: a single upload target (the FE uploads only the original; the backend generates
    # the thumbnail on register).
    signed = await svc.create_upload_url(school_id=_S1, event_id=_E1)
    assert signed.object_path.startswith("events/s1/e1/")
    assert signed.upload_url


async def test_upload_url_missing_event_raises() -> None:
    svc, _ = _svc(events=[])
    with pytest.raises(NotFoundError):
        await svc.create_upload_url(school_id=_S1, event_id="ghost")


async def test_upload_url_archived_event_rejected() -> None:
    svc, _ = _svc(
        events=[make_event(id=_E1, school_id=_S1, status=EventStatus.ARCHIVED)]
    )
    with pytest.raises(ValidationError):
        await svc.create_upload_url(school_id=_S1, event_id=_E1)


# ---- register (records only) ------------------------------------------


async def test_register_media_records_pending() -> None:
    svc, mrepo = _svc()
    media = await svc.register_media(
        school_id=_S1, event_id=_E1, storage_path=_PATH, media_type=MediaType.VIDEO
    )
    assert media.processing_status is MediaProcessingStatus.PENDING
    assert media.media_type is MediaType.VIDEO
    assert [m.id for m in await mrepo.list_by_event(_S1, _E1)] == [media.id]


async def test_register_media_path_outside_event_prefix_rejected() -> None:
    svc, mrepo = _svc()
    with pytest.raises(ValidationError):
        await svc.register_media(
            school_id=_S1, event_id=_E1,
            storage_path="events/other/e1/photo.jpg", media_type=MediaType.IMAGE,
        )
    assert not await mrepo.list_by_event(_S1, _E1)  # nothing written


async def test_register_media_missing_event_raises() -> None:
    svc, mrepo = _svc(events=[])
    with pytest.raises(NotFoundError):
        await svc.register_media(
            school_id=_S1, event_id="ghost",
            storage_path="events/s1/ghost/p.jpg", media_type=MediaType.IMAGE,
        )


async def test_register_media_archived_event_rejected() -> None:
    svc, _ = _svc(
        events=[make_event(id=_E1, school_id=_S1, status=EventStatus.ARCHIVED)]
    )
    with pytest.raises(ValidationError):
        await svc.register_media(
            school_id=_S1, event_id=_E1, storage_path=_PATH, media_type=MediaType.IMAGE
        )


# ---- reads + tenant isolation -----------------------------------------


async def test_get_media_is_tenant_scoped() -> None:
    svc, _ = _svc(media=[make_media(id="m1", school_id=_S1, event_id=_E1)])
    assert (await svc.get_media(school_id=_S1, media_id="m1")).id == "m1"
    with pytest.raises(NotFoundError):
        await svc.get_media(school_id="other", media_id="m1")


async def test_list_event_media_missing_event_404() -> None:
    svc, _ = _svc(events=[])
    with pytest.raises(NotFoundError):
        await svc.list_event_media(school_id=_S1, event_id="ghost")


async def test_list_event_media_returns_event_photos() -> None:
    svc, _ = _svc(
        media=[
            make_media(id="m1", school_id=_S1, event_id=_E1),
            make_media(id="m2", school_id=_S1, event_id=_E1),
        ]
    )
    assert {m.id for m in await svc.list_event_media(school_id=_S1, event_id=_E1)} == {
        "m1",
        "m2",
    }
