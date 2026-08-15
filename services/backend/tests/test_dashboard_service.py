"""DashboardService use-case with fakes (BP1, decisions/0038).

Verifies the school command center composes the grouped counts correctly: enrollment
rollup, event lifecycle/in-flight rollup, photo totals, and the two needs-attention
signals (events with photos but never distributed; matches needing review).
"""

from __future__ import annotations

from datetime import UTC, datetime

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
    Role,
    School,
    Student,
    User,
)
from backend.services.dashboard_service import DashboardService
from backend_fakes import (
    FakeEventRepo,
    FakeMatchCorrectionRepo,
    FakeMediaRepo,
    FakeMlResultsReader,
    FakeSchoolRepo,
    FakeStudentRepo,
    FakeUserRepo,
    make_appearance,
    make_event,
    make_match_correction,
    make_media,
    make_school,
    make_student,
    make_user,
)

_S1 = "s1"
_DT = datetime(2026, 1, 1, tzinfo=UTC)  # an "announced"/completed timestamp


def _svc(
    *,
    schools: list[School] | None = None,
    students: list[Student] | None = None,
    events: list[Event] | None = None,
    media: list[Media] | None = None,
    appearances: list[Appearance] | None = None,
    corrections: list[MatchCorrection] | None = None,
    users: list[User] | None = None,
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
        FakeUserRepo(users or []),
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


async def test_in_flight_event_with_pending_media_is_not_flagged() -> None:
    # BP19c: an event currently being worked (queued/processing) with pending media must NOT
    # surface as "photos to process" — it's already in flight. Guards the fake's in_flight skip.
    for st in (EventProcessingStatus.QUEUED, EventProcessingStatus.PROCESSING):
        svc = _svc(
            events=[make_event(id="e1", school_id=_S1, processing_status=st)],
            media=[make_media(id="m1", school_id=_S1, event_id="e1",
                              processing_status=MediaProcessingStatus.PENDING)],
        )
        d = await svc.school_summary(school_id=_S1)
        assert d.events_undistributed == 0


async def test_completed_event_with_a_second_batch_is_flagged() -> None:
    # BP19c widening: a completed event that got NEW pending photos (a second batch) is now
    # surfaced — the old never-processed-only predicate missed it.
    svc = _svc(
        events=[make_event(id="e1", school_id=_S1,
                           processing_status=EventProcessingStatus.COMPLETED)],
        media=[
            make_media(id="done", school_id=_S1, event_id="e1",
                       processing_status=MediaProcessingStatus.COMPLETED),
            make_media(id="new", school_id=_S1, event_id="e1",
                       processing_status=MediaProcessingStatus.PENDING),
        ],
    )
    d = await svc.school_summary(school_id=_S1)
    assert d.events_undistributed == 1


async def test_dashboard_surfaces_failed_photos_not_all_processed() -> None:
    # BP19c: failed photos are counted (no more "All processed" over them). A completed event
    # with only completed+failed media (0 pending) is NOT a "photos to process" alert.
    svc = _svc(
        events=[make_event(id="e1", school_id=_S1,
                           processing_status=EventProcessingStatus.COMPLETED)],
        media=[
            make_media(id="ok", school_id=_S1, event_id="e1",
                       processing_status=MediaProcessingStatus.COMPLETED),
            make_media(id="bad", school_id=_S1, event_id="e1",
                       processing_status=MediaProcessingStatus.FAILED),
        ],
    )
    d = await svc.school_summary(school_id=_S1)
    assert d.photos_failed == 1
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


# --- setup checklist (BP7a) ---


async def test_setup_checklist_signals_reflect_first_run_progress() -> None:
    # A fresh school: no teacher, nothing announced.
    d0 = await _svc().school_summary(school_id=_S1)
    assert d0.has_staff is False
    assert d0.has_distributed is False

    # A teacher added -> has_staff; a manually-notified event -> has_distributed.
    svc = _svc(
        users=[make_user(id="t1", school_id=_S1, role=Role.TEACHER)],
        events=[make_event(id="e1", school_id=_S1, notified_at=_DT)],
    )
    d = await svc.school_summary(school_id=_S1)
    assert d.has_staff is True
    assert d.has_distributed is True


async def test_has_staff_needs_a_teacher_not_just_an_admin() -> None:
    # The "add a teacher" step isn't ticked by the school's own admin login.
    svc = _svc(users=[make_user(id="a1", school_id=_S1, role=Role.SCHOOL_ADMIN)])
    assert (await svc.school_summary(school_id=_S1)).has_staff is False


async def test_has_distributed_counts_auto_announced_completed_event() -> None:
    # No manual notify, but auto_notify + a completion time => announced (BP4 predicate).
    svc = _svc(events=[make_event(id="e1", school_id=_S1, auto_notify=True,
                                  completed_at=_DT,
                                  processing_status=EventProcessingStatus.COMPLETED)])
    assert (await svc.school_summary(school_id=_S1)).has_distributed is True

    # auto_notify but not yet completed => not announced.
    svc2 = _svc(events=[make_event(id="e1", school_id=_S1, auto_notify=True,
                                   completed_at=None)])
    assert (await svc2.school_summary(school_id=_S1)).has_distributed is False

    # completed but auto_notify off and never manually notified => not announced.
    svc3 = _svc(events=[make_event(id="e1", school_id=_S1, auto_notify=False,
                                   completed_at=_DT, notified_at=None)])
    assert (await svc3.school_summary(school_id=_S1)).has_distributed is False


async def test_setup_checklist_signals_are_tenant_scoped() -> None:
    # A teacher / announced event in another school must not tick s1's checklist.
    svc = _svc(
        users=[make_user(id="t2", school_id="s2", role=Role.TEACHER)],
        events=[make_event(id="e2", school_id="s2", notified_at=_DT)],
    )
    d = await svc.school_summary(school_id=_S1)
    assert d.has_staff is False
    assert d.has_distributed is False


async def test_setup_checklist_all_steps_complete_is_the_retire_state() -> None:
    # Every checklist step satisfied — the composite state that retires the FE card.
    svc = _svc(
        users=[make_user(id="t1", school_id=_S1, role=Role.TEACHER)],
        students=[make_student(id="a", school_id=_S1, user_id="ua",
                               enrollment_status=EnrollmentStatus.ENROLLED)],
        events=[make_event(id="e1", school_id=_S1, notified_at=_DT,
                           processing_status=EventProcessingStatus.COMPLETED)],
        media=[make_media(id="m1", school_id=_S1, event_id="e1")],
    )
    d = await svc.school_summary(school_id=_S1)
    assert d.has_staff is True
    assert d.has_distributed is True
    # The three derived (schema-composed) signals:
    assert d.students_enrolled > 0  # -> has_enrolled_student
    assert d.events_total > 0  # -> has_event
    assert d.photos_total > 0  # -> has_media
