"""EventService use-cases with fakes (decisions/0027)."""

from __future__ import annotations

from datetime import date

import pytest
from backend.domain.errors import NotFoundError, UpstreamError, ValidationError
from backend.domain.models import (
    Event,
    EventProcessingStatus,
    EventStatus,
    Media,
    MediaProcessingStatus,
)
from backend.services.event_service import EventService
from backend_fakes import (
    FakeEventJobProducer,
    FakeEventRepo,
    FakeMediaRepo,
    make_event,
    make_media,
)

_S1 = "s1"
_E1 = "e1"


def _svc(
    *,
    events: list[Event] | None = None,
    media: list[Media] | None = None,
    producer: FakeEventJobProducer | None = None,
) -> tuple[EventService, FakeEventRepo, FakeMediaRepo, FakeEventJobProducer]:
    erepo = FakeEventRepo(events or [])
    mrepo = FakeMediaRepo(media or [])
    prod = producer or FakeEventJobProducer()
    return EventService(erepo, mrepo, prod), erepo, mrepo, prod


# ---- CRUD --------------------------------------------------------------


async def test_create_event_trims_name_and_defaults_not_started() -> None:
    svc, _, _, _ = _svc()
    event = await svc.create_event(
        school_id=_S1, name="  Sports Day ", description="fun",
        event_date=date(2026, 6, 1), created_by="u1",
    )
    assert event.name == "Sports Day" and event.school_id == _S1
    assert event.status is EventStatus.ACTIVE
    assert event.processing_status is EventProcessingStatus.NOT_STARTED


async def test_create_event_empty_name_rejected() -> None:
    svc, _, _, _ = _svc()
    with pytest.raises(ValidationError):
        await svc.create_event(
            school_id=_S1, name="   ", description=None, event_date=None,
            created_by="u1",
        )


async def test_get_event_is_tenant_scoped() -> None:
    svc, _, _, _ = _svc(events=[make_event(id=_E1, school_id=_S1)])
    assert (await svc.get_event(school_id=_S1, event_id=_E1)).id == _E1
    with pytest.raises(NotFoundError):
        await svc.get_event(school_id="other", event_id=_E1)


async def test_list_events_only_own_school() -> None:
    svc, _, _, _ = _svc(
        events=[make_event(id=_E1, school_id=_S1), make_event(id="e2", school_id="s2")]
    )
    assert {e.id for e in await svc.list_events(school_id=_S1)} == {_E1}


async def test_update_event_archives_and_renames() -> None:
    svc, _, _, _ = _svc(events=[make_event(id=_E1, school_id=_S1, name="Old")])
    updated = await svc.update_event(
        school_id=_S1, event_id=_E1, name="New", status=EventStatus.ARCHIVED
    )
    assert updated.name == "New" and updated.status is EventStatus.ARCHIVED


async def test_update_missing_event_raises() -> None:
    svc, _, _, _ = _svc()
    with pytest.raises(NotFoundError):
        await svc.update_event(school_id=_S1, event_id="ghost", name="X")


# ---- process / redistribute -------------------------------------------


async def test_process_event_enqueues_one_event_job_and_queues() -> None:
    svc, erepo, _, prod = _svc(
        events=[make_event(id=_E1, school_id=_S1)],
        media=[make_media(id="m1", school_id=_S1, event_id=_E1)],  # pending
    )
    event = await svc.process_event(school_id=_S1, event_id=_E1)
    assert event.processing_status is EventProcessingStatus.QUEUED
    assert event.enqueued_at is not None
    # Exactly one EVENT job — {school_id, event_id}, no photos.
    assert len(prod.jobs) == 1
    assert prod.jobs[0].school_id == _S1 and prod.jobs[0].event_id == _E1


async def test_process_event_with_no_pending_photos_rejected() -> None:
    svc, _, _, prod = _svc(
        events=[make_event(id=_E1, school_id=_S1)],
        media=[
            make_media(id="m1", school_id=_S1, event_id=_E1,
                       processing_status=MediaProcessingStatus.COMPLETED)
        ],
    )
    with pytest.raises(ValidationError):
        await svc.process_event(school_id=_S1, event_id=_E1)
    assert prod.jobs == []  # nothing enqueued


async def test_process_empty_event_rejected() -> None:
    svc, _, _, prod = _svc(events=[make_event(id=_E1, school_id=_S1)])
    with pytest.raises(ValidationError):
        await svc.process_event(school_id=_S1, event_id=_E1)
    assert prod.jobs == []


async def test_process_archived_event_rejected() -> None:
    svc, _, _, prod = _svc(
        events=[make_event(id=_E1, school_id=_S1, status=EventStatus.ARCHIVED)],
        media=[make_media(id="m1", school_id=_S1, event_id=_E1)],
    )
    with pytest.raises(ValidationError):
        await svc.process_event(school_id=_S1, event_id=_E1)
    assert prod.jobs == []


async def test_process_missing_event_raises() -> None:
    svc, _, _, _ = _svc()
    with pytest.raises(NotFoundError):
        await svc.process_event(school_id=_S1, event_id="ghost")


async def test_process_while_in_flight_rejected_no_duplicate_job() -> None:
    # An event already queued/processing must NOT be XADD'd again (0027).
    for status in (EventProcessingStatus.QUEUED, EventProcessingStatus.PROCESSING):
        svc, _, _, prod = _svc(
            events=[make_event(id=_E1, school_id=_S1, processing_status=status)],
            media=[make_media(id="m1", school_id=_S1, event_id=_E1)],  # pending
        )
        with pytest.raises(ValidationError):
            await svc.process_event(school_id=_S1, event_id=_E1)
        assert prod.jobs == []


async def test_redistribute_completed_event_with_leftover_pending() -> None:
    # A run finished (event completed) but a photo stayed pending (e.g. a fetch error):
    # re-pressing Process re-enqueues to retry the leftover (0027).
    svc, _, _, prod = _svc(
        events=[make_event(id=_E1, school_id=_S1,
                           processing_status=EventProcessingStatus.COMPLETED)],
        media=[
            make_media(id="m1", school_id=_S1, event_id=_E1),  # pending leftover
            make_media(id="m2", school_id=_S1, event_id=_E1,
                       processing_status=MediaProcessingStatus.COMPLETED),
        ],
    )
    event = await svc.process_event(school_id=_S1, event_id=_E1)
    assert event.processing_status is EventProcessingStatus.QUEUED
    assert len(prod.jobs) == 1


async def test_process_enqueue_failure_leaves_status_unchanged() -> None:
    prod = FakeEventJobProducer(raise_on_enqueue=UpstreamError("redis down"))
    svc, erepo, _, _ = _svc(
        producer=prod,
        events=[make_event(id=_E1, school_id=_S1)],
        media=[make_media(id="m1", school_id=_S1, event_id=_E1)],
    )
    with pytest.raises(UpstreamError):
        await svc.process_event(school_id=_S1, event_id=_E1)
    # Enqueue happens before the status flip, so the event never left not_started.
    event = await erepo.get(_S1, _E1)
    assert event is not None
    assert event.processing_status is EventProcessingStatus.NOT_STARTED


async def test_process_is_tenant_scoped() -> None:
    svc, _, _, _ = _svc(
        events=[make_event(id=_E1, school_id=_S1)],
        media=[make_media(id="m1", school_id=_S1, event_id=_E1)],
    )
    with pytest.raises(NotFoundError):
        await svc.process_event(school_id="other", event_id=_E1)


# ---- status ------------------------------------------------------------


async def test_event_status_reports_counts_and_processing_state() -> None:
    svc, _, _, _ = _svc(
        events=[make_event(id=_E1, school_id=_S1,
                           processing_status=EventProcessingStatus.PROCESSING)],
        media=[
            make_media(id="m1", school_id=_S1, event_id=_E1),  # pending
            make_media(id="m2", school_id=_S1, event_id=_E1,
                       processing_status=MediaProcessingStatus.COMPLETED),
        ],
    )
    view = await svc.event_status(school_id=_S1, event_id=_E1)
    assert view.event.processing_status is EventProcessingStatus.PROCESSING
    assert view.counts[MediaProcessingStatus.PENDING] == 1
    assert view.counts[MediaProcessingStatus.COMPLETED] == 1


async def test_event_status_missing_event_raises() -> None:
    svc, _, _, _ = _svc()
    with pytest.raises(NotFoundError):
        await svc.event_status(school_id=_S1, event_id="ghost")
