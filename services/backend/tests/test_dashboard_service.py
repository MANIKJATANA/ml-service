"""DashboardService use-case with fakes (BP1, decisions/0038).

Verifies the school command center composes the grouped counts correctly: enrollment
rollup, event lifecycle/in-flight rollup, photo totals, and the two needs-attention
signals (events with photos but never distributed; matches needing review).
"""

from __future__ import annotations

import pytest
from backend.domain.errors import NotFoundError
from backend.domain.models import (
    Appearance,
    EnrollmentStatus,
    Event,
    EventProcessingStatus,
    EventStatus,
    MatchCorrection,
    MatchVerdict,
    Media,
    MediaProcessingStatus,
    School,
    Student,
)
from backend.services.dashboard_service import DashboardService
from backend_fakes import (
    FakeEventRepo,
    FakeMatchCorrectionRepo,
    FakeMediaRepo,
    FakeMlResultsReader,
    FakeSchoolRepo,
    FakeStudentRepo,
    make_appearance,
    make_event,
    make_match_correction,
    make_media,
    make_school,
    make_student,
)

_S1 = "s1"


def _svc(
    *,
    schools: list[School] | None = None,
    students: list[Student] | None = None,
    events: list[Event] | None = None,
    media: list[Media] | None = None,
    appearances: list[Appearance] | None = None,
    corrections: list[MatchCorrection] | None = None,
) -> DashboardService:
    event_repo = FakeEventRepo(events or [])
    media_repo = FakeMediaRepo(media or [])
    # Mirror the SeededContainer wiring so the undistributed alert sees media presence.
    event_repo.link_media(media_repo)
    return DashboardService(
        FakeSchoolRepo(schools or [make_school(id=_S1, name="Springfield")]),
        FakeStudentRepo(students or []),
        event_repo,
        media_repo,
        FakeMlResultsReader(appearances or []),
        FakeMatchCorrectionRepo(corrections or []),
    )


async def test_school_summary_rolls_up_every_count() -> None:
    svc = _svc(
        students=[
            make_student(id="a", school_id=_S1, user_id="ua",
                         enrollment_status=EnrollmentStatus.ENROLLED),
            make_student(id="b", school_id=_S1, user_id="ub",
                         enrollment_status=EnrollmentStatus.ENROLLED),
            make_student(id="c", school_id=_S1, user_id="uc",
                         enrollment_status=EnrollmentStatus.PENDING),
            make_student(id="d", school_id=_S1, user_id="ud",
                         enrollment_status=EnrollmentStatus.FAILED),
        ],
        events=[
            # e1: not_started but has photos -> undistributed alert
            make_event(id="e1", school_id=_S1,
                       processing_status=EventProcessingStatus.NOT_STARTED),
            # e2: currently processing (in-flight)
            make_event(id="e2", school_id=_S1,
                       processing_status=EventProcessingStatus.PROCESSING),
            # e3: archived
            make_event(id="e3", school_id=_S1, status=EventStatus.ARCHIVED,
                       processing_status=EventProcessingStatus.COMPLETED),
        ],
        media=[
            make_media(id="m1", school_id=_S1, event_id="e1",
                       processing_status=MediaProcessingStatus.PENDING),
            make_media(id="m2", school_id=_S1, event_id="e2",
                       processing_status=MediaProcessingStatus.COMPLETED),
        ],
        appearances=[
            make_appearance(student_id="a", media_id="m2", event_id="e2",
                            needs_review=True),
            make_appearance(student_id="b", media_id="m2", event_id="e2",
                            needs_review=False),
        ],
    )

    d = await svc.school_summary(school_id=_S1)

    assert d.school_name == "Springfield"
    assert (d.students_total, d.students_enrolled, d.students_pending,
            d.students_failed) == (4, 2, 1, 1)
    assert (d.events_total, d.events_active, d.events_archived,
            d.events_processing) == (3, 2, 1, 1)
    assert (d.photos_total, d.photos_pending) == (2, 1)
    # e1 has a photo and is still not_started -> exactly one undistributed event.
    assert d.events_undistributed == 1
    # One of the two matches is flagged.
    assert d.needs_review == 1


async def test_school_summary_empty_school_is_all_zeroes() -> None:
    d = await _svc().school_summary(school_id=_S1)
    assert (d.students_total, d.events_total, d.photos_total) == (0, 0, 0)
    assert (d.events_undistributed, d.needs_review) == (0, 0)


async def test_not_started_event_without_media_is_not_flagged() -> None:
    # not_started but NO photos -> not an "undistributed" alert.
    svc = _svc(
        events=[make_event(id="e1", school_id=_S1,
                           processing_status=EventProcessingStatus.NOT_STARTED)],
        media=[],
    )
    d = await svc.school_summary(school_id=_S1)
    assert d.events_undistributed == 0


async def test_archived_not_started_event_with_media_is_not_flagged() -> None:
    # An archived event can't be Processed (route 400s), so even not_started + media
    # must NOT surface as "ready to distribute".
    svc = _svc(
        events=[make_event(id="e1", school_id=_S1, status=EventStatus.ARCHIVED,
                           processing_status=EventProcessingStatus.NOT_STARTED)],
        media=[make_media(id="m1", school_id=_S1, event_id="e1")],
    )
    d = await svc.school_summary(school_id=_S1)
    assert d.events_undistributed == 0


async def test_needs_review_subtracts_resolved_corrections_and_clamps() -> None:
    # BP5: the "needs review" signal is raw flagged matches MINUS resolved corrections,
    # clamped at 0 (so review-churn can never drive it negative).
    events = [make_event(id="e1", school_id=_S1,
                         processing_status=EventProcessingStatus.COMPLETED)]
    appearances = [
        make_appearance(student_id="a", media_id="m1", event_id="e1", needs_review=True),
        make_appearance(student_id="b", media_id="m1", event_id="e1", needs_review=True),
    ]
    # One flag resolved by staff -> count drops from 2 to 1.
    svc = _svc(
        events=events,
        appearances=appearances,
        corrections=[
            make_match_correction(media_id="m1", student_id="a", event_id="e1",
                                  verdict=MatchVerdict.CONFIRMED, resolves_review=True),
        ],
    )
    assert (await svc.school_summary(school_id=_S1)).needs_review == 1

    # More resolutions than raw flags (re-inference churn) -> clamps at 0, never negative.
    svc2 = _svc(
        events=events,
        appearances=appearances,
        corrections=[
            make_match_correction(media_id="m1", student_id="a", event_id="e1",
                                  verdict=MatchVerdict.CONFIRMED, resolves_review=True),
            make_match_correction(media_id="m1", student_id="b", event_id="e1",
                                  verdict=MatchVerdict.REJECTED, resolves_review=True),
            make_match_correction(media_id="m9", student_id="c", event_id="e1",
                                  verdict=MatchVerdict.REJECTED, resolves_review=True),
        ],
    )
    assert (await svc2.school_summary(school_id=_S1)).needs_review == 0


async def test_counts_are_tenant_scoped() -> None:
    # A student in another school must not leak into s1's rollup.
    svc = _svc(
        students=[
            make_student(id="a", school_id=_S1, user_id="ua",
                         enrollment_status=EnrollmentStatus.ENROLLED),
            make_student(id="z", school_id="s2", user_id="uz",
                         enrollment_status=EnrollmentStatus.ENROLLED),
        ],
    )
    d = await svc.school_summary(school_id=_S1)
    assert d.students_total == 1


async def test_missing_school_raises_not_found() -> None:
    svc = _svc(schools=[make_school(id="other", name="Other")])
    with pytest.raises(NotFoundError):
        await svc.school_summary(school_id=_S1)
