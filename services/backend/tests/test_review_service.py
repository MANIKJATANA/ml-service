"""ReviewService use-cases with fakes (BP5, decisions/0042).

Covers confirm/reject (+ resolves_review), report-a-miss (added, and 'already matched ->
confirmed'), student self-reject (incl. the 404-if-not-appearing gate + overriding an
`added`), undo, and the review lane.
"""

from __future__ import annotations

import pytest
from backend.domain.errors import NotFoundError
from backend.domain.models import (
    Appearance,
    Event,
    MatchVerdict,
    Media,
    Student,
)
from backend.services.review_service import ReviewService
from backend_fakes import (
    FakeEventRepo,
    FakeMatchCorrectionRepo,
    FakeMediaRepo,
    FakeMlResultsReader,
    FakeStudentRepo,
    make_appearance,
    make_event,
    make_match_correction,
    make_media,
    make_student,
)

_S1 = "s1"


def _svc(
    *,
    appearances: list[Appearance] | None = None,
    corrections: FakeMatchCorrectionRepo | None = None,
    media: list[Media] | None = None,
    students: list[Student] | None = None,
    events: list[Event] | None = None,
) -> tuple[ReviewService, FakeMatchCorrectionRepo]:
    corr = corrections if corrections is not None else FakeMatchCorrectionRepo()
    svc = ReviewService(
        FakeMlResultsReader(appearances or []),
        corr,
        FakeMediaRepo(media or [make_media(id="m1", school_id=_S1, event_id="e1")]),
        FakeStudentRepo(students or [make_student(id="a", school_id=_S1, user_id="ua")]),
        FakeEventRepo(events or [make_event(id="e1", school_id=_S1)]),
    )
    return svc, corr


# ---- confirm / reject --------------------------------------------------


async def test_reject_ambiguous_match_stamps_resolves_review() -> None:
    svc, corr = _svc(
        appearances=[
            make_appearance(student_id="a", media_id="m1", event_id="e1", needs_review=True)
        ]
    )
    await svc.set_verdict(
        school_id=_S1, media_id="m1", student_id="a",
        verdict=MatchVerdict.REJECTED, corrected_by="staff",
    )
    c = await corr.get(_S1, "m1", "a")
    assert c is not None
    assert c.verdict is MatchVerdict.REJECTED and c.resolves_review is True


async def test_confirm_non_ambiguous_does_not_resolve_review() -> None:
    svc, corr = _svc(
        appearances=[
            make_appearance(student_id="a", media_id="m1", event_id="e1", needs_review=False)
        ]
    )
    await svc.set_verdict(
        school_id=_S1, media_id="m1", student_id="a",
        verdict=MatchVerdict.CONFIRMED, corrected_by="staff",
    )
    c = await corr.get(_S1, "m1", "a")
    assert c is not None and c.resolves_review is False


# ---- report-a-miss -----------------------------------------------------


async def test_add_missed_records_added() -> None:
    svc, corr = _svc(
        students=[make_student(id="b", school_id=_S1, user_id="ub")],
        appearances=[],
    )
    await svc.add_missed(
        school_id=_S1, media_id="m1", student_id="b", corrected_by="staff"
    )
    c = await corr.get(_S1, "m1", "b")
    assert c is not None and c.verdict is MatchVerdict.ADDED and c.event_id == "e1"


async def test_add_missed_of_already_matched_is_confirmed() -> None:
    svc, corr = _svc(
        appearances=[
            make_appearance(student_id="a", media_id="m1", event_id="e1", needs_review=True)
        ]
    )
    await svc.add_missed(
        school_id=_S1, media_id="m1", student_id="a", corrected_by="staff"
    )
    c = await corr.get(_S1, "m1", "a")
    assert c is not None and c.verdict is MatchVerdict.CONFIRMED and c.resolves_review is True


# ---- student self-reject -----------------------------------------------


async def test_self_reject_of_a_real_match() -> None:
    svc, corr = _svc(
        appearances=[make_appearance(student_id="a", media_id="m1", event_id="e1")]
    )
    await svc.self_reject(
        school_id=_S1, media_id="m1", student_id="a", corrected_by="user-a"
    )
    c = await corr.get(_S1, "m1", "a")
    assert c is not None and c.verdict is MatchVerdict.REJECTED


async def test_self_reject_when_not_appearing_raises() -> None:
    svc, _ = _svc(appearances=[])  # a doesn't appear in m1
    with pytest.raises(NotFoundError):
        await svc.self_reject(
            school_id=_S1, media_id="m1", student_id="a", corrected_by="user-a"
        )


async def test_self_reject_overrides_a_staff_added() -> None:
    # Staff added the student (they're effective via the added row) -> self-reject wins.
    corr = FakeMatchCorrectionRepo(
        [
            make_match_correction(
                media_id="m1", student_id="a", event_id="e1", verdict=MatchVerdict.ADDED
            )
        ]
    )
    svc, corr = _svc(appearances=[], corrections=corr)
    await svc.self_reject(
        school_id=_S1, media_id="m1", student_id="a", corrected_by="user-a"
    )
    c = await corr.get(_S1, "m1", "a")
    assert c is not None and c.verdict is MatchVerdict.REJECTED


# ---- undo --------------------------------------------------------------


async def test_delete_correction_reverts_to_ml_truth() -> None:
    corr = FakeMatchCorrectionRepo(
        [
            make_match_correction(
                media_id="m1", student_id="a", event_id="e1", verdict=MatchVerdict.REJECTED
            )
        ]
    )
    svc, corr = _svc(corrections=corr)
    await svc.delete_correction(school_id=_S1, media_id="m1", student_id="a")
    assert await corr.get(_S1, "m1", "a") is None


# ---- review lane -------------------------------------------------------


async def test_event_review_lists_unresolved_ambiguous_grouped_by_media() -> None:
    corr = FakeMatchCorrectionRepo(
        # b's ambiguous match in m1 is already resolved -> excluded from the lane.
        [
            make_match_correction(
                media_id="m1", student_id="b", event_id="e1", verdict=MatchVerdict.REJECTED
            )
        ]
    )
    svc, _ = _svc(
        media=[
            make_media(id="m1", school_id=_S1, event_id="e1"),
            make_media(id="m2", school_id=_S1, event_id="e1"),
        ],
        students=[
            make_student(id="a", school_id=_S1, user_id="ua"),
            make_student(id="b", school_id=_S1, user_id="ub"),
        ],
        appearances=[
            make_appearance(student_id="a", media_id="m1", event_id="e1", needs_review=True),
            make_appearance(student_id="b", media_id="m1", event_id="e1", needs_review=True),
            make_appearance(student_id="a", media_id="m2", event_id="e1", needs_review=False),
        ],
        corrections=corr,
    )
    reviews = await svc.event_review(school_id=_S1, event_id="e1")
    assert len(reviews) == 1  # only m1 has an unresolved ambiguous match (m2 not ambiguous)
    assert reviews[0].media.id == "m1"
    assert [c.student.id for c in reviews[0].candidates] == ["a"]  # b resolved
