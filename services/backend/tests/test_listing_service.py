"""ListingService use-cases with fakes (BP2, decisions/0039).

Covers the count-rich lists: events + per-event counts, students + per-student counts,
the platform schools rollups + a school's admin roster, and tenant/scope behavior.
"""

from __future__ import annotations

import pytest
from backend.domain.errors import NotFoundError
from backend.domain.models import (
    Appearance,
    Event,
    Media,
    MediaProcessingStatus,
    Role,
    School,
    Student,
    User,
)
from backend.services.listing_service import ListingService
from backend_fakes import (
    FakeEventRepo,
    FakeMediaRepo,
    FakeMlResultsReader,
    FakeSchoolRepo,
    FakeStudentRepo,
    FakeUserRepo,
    make_appearance,
    make_event,
    make_media,
    make_school,
    make_student,
    make_user,
)

_S1 = "s1"


def _svc(
    *,
    schools: list[School] | None = None,
    users: list[User] | None = None,
    students: list[Student] | None = None,
    events: list[Event] | None = None,
    media: list[Media] | None = None,
    appearances: list[Appearance] | None = None,
) -> ListingService:
    return ListingService(
        FakeSchoolRepo(schools or []),
        FakeUserRepo(users or []),
        FakeStudentRepo(students or []),
        FakeEventRepo(events or []),
        FakeMediaRepo(media or []),
        FakeMlResultsReader(appearances or []),
    )


# ---- events + counts ---------------------------------------------------


async def test_list_events_carries_photo_and_match_counts() -> None:
    svc = _svc(
        events=[make_event(id="e1", school_id=_S1), make_event(id="e2", school_id=_S1)],
        media=[
            make_media(id="m1", school_id=_S1, event_id="e1"),
            make_media(id="m2", school_id=_S1, event_id="e1"),
        ],
        appearances=[
            make_appearance(student_id="a", media_id="m1", event_id="e1"),
            make_appearance(student_id="b", media_id="m1", event_id="e1", needs_review=True),
            make_appearance(student_id="a", media_id="m2", event_id="e1"),
        ],
    )
    listings = {x.event.id: x for x in await svc.list_events(school_id=_S1)}
    # e1: 2 photos, 2 distinct matched students (a, b), 1 review-flagged match.
    assert (listings["e1"].media_count, listings["e1"].matched_students,
            listings["e1"].needs_review) == (2, 2, 1)
    # e2: nothing yet — all zero, still present in the list.
    assert (listings["e2"].media_count, listings["e2"].matched_students,
            listings["e2"].needs_review) == (0, 0, 0)
    # BP19c: both e1 photos are pending (make_media default); e2 has none.
    assert listings["e1"].pending == 2 and listings["e2"].pending == 0


async def test_list_events_pending_flags_a_second_batch() -> None:
    # BP19c: the events list must be able to tell an already-completed event apart from one
    # with a second batch of new (pending) photos — via the per-event pending count.
    svc = _svc(
        events=[make_event(id="e1", school_id=_S1)],
        media=[
            make_media(id="done", school_id=_S1, event_id="e1",
                       processing_status=MediaProcessingStatus.COMPLETED),
            make_media(id="new", school_id=_S1, event_id="e1",
                       processing_status=MediaProcessingStatus.PENDING),
        ],
    )
    listing = (await svc.list_events(school_id=_S1))[0]
    assert listing.media_count == 2 and listing.pending == 1


# ---- students + counts -------------------------------------------------


async def test_list_students_carries_appearance_and_event_counts() -> None:
    svc = _svc(
        students=[
            make_student(id="st1", school_id=_S1, user_id="u1"),
            make_student(id="st2", school_id=_S1, user_id="u2"),
        ],
        appearances=[
            make_appearance(student_id="st1", media_id="m1", event_id="e1"),
            make_appearance(student_id="st1", media_id="m2", event_id="e1"),
            make_appearance(student_id="st1", media_id="m3", event_id="e2"),
            # A match for a since-deleted student not in the roster — must be ignored,
            # never a KeyError (the service iterates rows, not count keys).
            make_appearance(student_id="ghost", media_id="m9", event_id="e1"),
        ],
    )
    listings = {x.student.id: x for x in await svc.list_students(school_id=_S1)}
    assert set(listings) == {"st1", "st2"}  # the ghost's extra count key is dropped
    # st1: 3 appearances across 2 distinct events.
    assert (listings["st1"].appearance_count, listings["st1"].event_count) == (3, 2)
    # st2: no matches — zeroes, still listed.
    assert (listings["st2"].appearance_count, listings["st2"].event_count) == (0, 0)


# ---- platform schools rollups ------------------------------------------


async def test_list_schools_rolls_up_admins_teachers_students_events() -> None:
    svc = _svc(
        schools=[make_school(id=_S1, name="A"), make_school(id="s2", name="B")],
        users=[
            make_user(id="u1", school_id=_S1, role=Role.SCHOOL_ADMIN),
            make_user(id="u2", school_id=_S1, role=Role.TEACHER),
            make_user(id="u3", school_id=_S1, role=Role.TEACHER),
            make_user(id="p", school_id=None, role=Role.PLATFORM_ADMIN),  # excluded
            make_user(id="u4", school_id="s2", role=Role.SCHOOL_ADMIN),
        ],
        students=[
            make_student(id="st1", school_id=_S1, user_id="x1"),
            make_student(id="st2", school_id="s2", user_id="x2"),
        ],
        events=[make_event(id="e1", school_id=_S1)],
    )
    rollups = {x.school.id: x.rollup for x in await svc.list_schools()}
    assert (rollups[_S1].admins, rollups[_S1].teachers, rollups[_S1].students,
            rollups[_S1].events) == (1, 2, 1, 1)
    assert (rollups["s2"].admins, rollups["s2"].teachers, rollups["s2"].students,
            rollups["s2"].events) == (1, 0, 1, 0)


async def test_get_school_returns_its_rollup() -> None:
    svc = _svc(
        schools=[make_school(id=_S1, name="A")],
        users=[make_user(id="u1", school_id=_S1, role=Role.SCHOOL_ADMIN)],
    )
    listing = await svc.get_school(school_id=_S1)
    assert listing.school.name == "A"
    assert listing.rollup.admins == 1


async def test_get_school_missing_raises() -> None:
    with pytest.raises(NotFoundError):
        await _svc().get_school(school_id="nope")


# ---- admin roster ------------------------------------------------------


async def test_list_school_admins_returns_only_admins() -> None:
    svc = _svc(
        schools=[make_school(id=_S1)],
        users=[
            make_user(id="a1", school_id=_S1, role=Role.SCHOOL_ADMIN, email="a1@x.io"),
            make_user(id="a2", school_id=_S1, role=Role.SCHOOL_ADMIN, email="a2@x.io"),
            make_user(id="t1", school_id=_S1, role=Role.TEACHER, email="t1@x.io"),
        ],
    )
    admins = await svc.list_school_admins(school_id=_S1)
    assert {u.email for u in admins} == {"a1@x.io", "a2@x.io"}


async def test_list_school_admins_missing_school_raises() -> None:
    with pytest.raises(NotFoundError):
        await _svc().list_school_admins(school_id="nope")
