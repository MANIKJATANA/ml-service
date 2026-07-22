"""GalleryService use-cases with fakes (decisions/0028).

Covers the two views + browse (event→students, event→student→photos, student→events,
student→photos), media→appearances, and entitlement-gated download. Tenant isolation is
enforced by the require-guards (foreign ids resolve to NotFound via the scoped repos).
"""

from __future__ import annotations

import pytest
from backend.domain.errors import NotFoundError
from backend.domain.models import (
    Appearance,
    Event,
    MatchCorrection,
    MatchVerdict,
    Media,
    Student,
)
from backend.services.gallery_service import GalleryService
from backend_fakes import (
    FakeDownloadAuditRepo,
    FakeEventRepo,
    FakeMatchCorrectionRepo,
    FakeMediaRepo,
    FakeMlResultsReader,
    FakeObjectStore,
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
    students: list[Student] | None = None,
    events: list[Event] | None = None,
    media: list[Media] | None = None,
    appearances: list[Appearance] | None = None,
    corrections: list[MatchCorrection] | None = None,
    audit: FakeDownloadAuditRepo | None = None,
    ttl: int = 3600,
) -> GalleryService:
    return GalleryService(
        FakeMlResultsReader(appearances or []),
        FakeStudentRepo(students or []),
        FakeEventRepo(events or []),
        FakeMediaRepo(media or []),
        FakeMatchCorrectionRepo(corrections or []),
        FakeObjectStore(),
        audit or FakeDownloadAuditRepo(),
        download_url_ttl_s=ttl,
    )


# ---- event → students --------------------------------------------------


async def test_event_students_groups_counts_and_keeps_only_appearing() -> None:
    svc = _svc(
        students=[
            make_student(id="a", school_id=_S1, user_id="ua", name="Ann"),
            make_student(id="b", school_id=_S1, user_id="ub", name="Bob"),
            make_student(id="c", school_id=_S1, user_id="uc", name="Cid"),  # no matches
        ],
        events=[make_event(id="e1", school_id=_S1)],
        appearances=[
            make_appearance(student_id="a", media_id="m1", event_id="e1"),
            make_appearance(student_id="a", media_id="m2", event_id="e1"),
            make_appearance(student_id="b", media_id="m1", event_id="e1"),
        ],
    )
    views = await svc.event_students(school_id=_S1, event_id="e1")
    # Only appearing students, in roster order, with per-student media counts.
    assert [(v.student.id, v.media_count) for v in views] == [("a", 2), ("b", 1)]


async def test_event_students_missing_event_raises() -> None:
    svc = _svc(events=[])
    with pytest.raises(NotFoundError):
        await svc.event_students(school_id=_S1, event_id="ghost")


async def test_event_students_tenant_scoped() -> None:
    svc = _svc(events=[make_event(id="e1", school_id=_S1)])
    with pytest.raises(NotFoundError):
        await svc.event_students(school_id="other", event_id="e1")


# ---- event → student → photos ------------------------------------------


async def test_event_student_media_returns_only_that_students_photos() -> None:
    svc = _svc(
        students=[make_student(id="a", school_id=_S1, user_id="ua")],
        events=[make_event(id="e1", school_id=_S1)],
        media=[
            make_media(id="m1", school_id=_S1, event_id="e1"),
            make_media(id="m2", school_id=_S1, event_id="e1"),
            make_media(id="m3", school_id=_S1, event_id="e1"),
        ],
        appearances=[
            make_appearance(student_id="a", media_id="m1", event_id="e1"),
            make_appearance(student_id="a", media_id="m3", event_id="e1"),
            make_appearance(student_id="b", media_id="m2", event_id="e1"),
        ],
    )
    media = await svc.event_student_media(
        school_id=_S1, event_id="e1", student_id="a"
    )
    assert {m.id for m in media} == {"m1", "m3"}


async def test_event_student_media_missing_student_raises() -> None:
    svc = _svc(events=[make_event(id="e1", school_id=_S1)], students=[])
    with pytest.raises(NotFoundError):
        await svc.event_student_media(school_id=_S1, event_id="e1", student_id="ghost")


# ---- student → events --------------------------------------------------


async def test_student_events_groups_counts_and_keeps_only_appearing() -> None:
    svc = _svc(
        students=[make_student(id="a", school_id=_S1, user_id="ua")],
        events=[
            make_event(id="e1", school_id=_S1),
            make_event(id="e2", school_id=_S1),
            make_event(id="e3", school_id=_S1),  # student not in it
        ],
        appearances=[
            make_appearance(student_id="a", media_id="m1", event_id="e1"),
            make_appearance(student_id="a", media_id="m2", event_id="e1"),
            make_appearance(student_id="a", media_id="m3", event_id="e2"),
        ],
    )
    views = await svc.student_events(school_id=_S1, student_id="a")
    assert [(v.event.id, v.media_count) for v in views] == [("e1", 2), ("e2", 1)]


# ---- student → photos --------------------------------------------------


async def test_student_media_all_and_filtered_by_event() -> None:
    svc = _svc(
        students=[make_student(id="a", school_id=_S1, user_id="ua")],
        events=[make_event(id="e1", school_id=_S1), make_event(id="e2", school_id=_S1)],
        media=[
            make_media(id="m1", school_id=_S1, event_id="e1"),
            make_media(id="m2", school_id=_S1, event_id="e1"),
            make_media(id="m3", school_id=_S1, event_id="e2"),
        ],
        appearances=[
            make_appearance(student_id="a", media_id="m1", event_id="e1"),
            make_appearance(student_id="a", media_id="m2", event_id="e1"),
            make_appearance(student_id="a", media_id="m3", event_id="e2"),
        ],
    )
    all_media = await svc.student_media(school_id=_S1, student_id="a")
    # Order follows the media repo (upload order), not match order — deterministic.
    assert [m.id for m in all_media] == ["m1", "m2", "m3"]

    e1_media = await svc.student_media(school_id=_S1, student_id="a", event_id="e1")
    assert [m.id for m in e1_media] == ["m1", "m2"]


async def test_student_media_missing_student_raises() -> None:
    svc = _svc(students=[])
    with pytest.raises(NotFoundError):
        await svc.student_media(school_id=_S1, student_id="ghost")


# ---- media → appearances -----------------------------------------------


async def test_media_appearances_joins_students_and_facts() -> None:
    svc = _svc(
        students=[
            make_student(id="a", school_id=_S1, user_id="ua", name="Ann"),
            make_student(id="b", school_id=_S1, user_id="ub", name="Bob"),
        ],
        media=[make_media(id="m1", school_id=_S1, event_id="e1")],
        appearances=[
            make_appearance(student_id="a", media_id="m1", confidence=0.9),
            make_appearance(
                student_id="b", media_id="m1", confidence=0.6, needs_review=True
            ),
        ],
    )
    views = await svc.media_appearances(school_id=_S1, media_id="m1")
    by_id = {v.student.id: v for v in views}
    assert by_id["a"].student.name == "Ann" and by_id["a"].needs_review is False
    assert by_id["b"].needs_review is True and by_id["b"].confidence == pytest.approx(0.6)


async def test_media_appearances_skips_since_deleted_student() -> None:
    # A matches row references a student no longer in the roster -> dropped, not an error.
    svc = _svc(
        students=[make_student(id="a", school_id=_S1, user_id="ua")],
        media=[make_media(id="m1", school_id=_S1, event_id="e1")],
        appearances=[
            make_appearance(student_id="a", media_id="m1"),
            make_appearance(student_id="gone", media_id="m1"),
        ],
    )
    views = await svc.media_appearances(school_id=_S1, media_id="m1")
    assert [v.student.id for v in views] == ["a"]


async def test_media_appearances_missing_media_raises() -> None:
    svc = _svc(media=[])
    with pytest.raises(NotFoundError):
        await svc.media_appearances(school_id=_S1, media_id="ghost")


# ---- download ----------------------------------------------------------


async def test_download_staff_any_media_in_school() -> None:
    svc = _svc(
        media=[make_media(id="m1", school_id=_S1, event_id="e1")],
        appearances=[],  # nobody matched — staff can still download
        ttl=120,
    )
    signed = await svc.download_url(
        school_id=_S1, media_id="m1", restrict_to_student_id=None
    )
    assert signed.expires_in_s == 120
    assert "events/school-1/event-1" in signed.download_url
    # The TTL must be threaded INTO the store call (the fake echoes it as ?ttl=),
    # not just copied onto the response — guards a dropped expires_in_s= arg.
    assert "ttl=120" in signed.download_url


async def test_download_missing_media_raises() -> None:
    svc = _svc(media=[])
    with pytest.raises(NotFoundError):
        await svc.download_url(
            school_id=_S1, media_id="ghost", restrict_to_student_id=None
        )


async def test_download_student_only_when_appearing() -> None:
    svc = _svc(
        media=[
            make_media(id="m1", school_id=_S1, event_id="e1"),
            make_media(id="m2", school_id=_S1, event_id="e1"),
        ],
        appearances=[make_appearance(student_id="a", media_id="m1")],
    )
    # Appears in m1 -> allowed.
    signed = await svc.download_url(
        school_id=_S1, media_id="m1", restrict_to_student_id="a"
    )
    assert signed.download_url
    # Does NOT appear in m2 -> 404 (never confirms the photo exists).
    with pytest.raises(NotFoundError):
        await svc.download_url(
            school_id=_S1, media_id="m2", restrict_to_student_id="a"
        )

# ---- BP5 correction overlay (decisions/0042) ---------------------------


async def test_download_blocked_for_rejected_match() -> None:
    svc = _svc(
        students=[make_student(id="a", school_id=_S1, user_id="ua")],
        media=[make_media(id="m1", school_id=_S1)],
        appearances=[make_appearance(student_id="a", media_id="m1", event_id="e1")],
        corrections=[
            make_match_correction(media_id="m1", student_id="a", verdict=MatchVerdict.REJECTED)
        ],
    )
    with pytest.raises(NotFoundError):
        await svc.download_url(
            school_id=_S1, media_id="m1", restrict_to_student_id="a"
        )


async def test_download_allowed_for_added_student() -> None:
    # No ML match, but staff added them (report-a-miss) -> they may download.
    svc = _svc(
        students=[make_student(id="a", school_id=_S1, user_id="ua")],
        media=[make_media(id="m1", school_id=_S1)],
        appearances=[],
        corrections=[
            make_match_correction(media_id="m1", student_id="a", verdict=MatchVerdict.ADDED)
        ],
    )
    signed = await svc.download_url(
        school_id=_S1, media_id="m1", restrict_to_student_id="a"
    )
    assert signed.download_url


async def test_download_allowed_for_plain_and_confirmed_match() -> None:
    svc = _svc(
        students=[make_student(id="a", school_id=_S1, user_id="ua")],
        media=[make_media(id="m1", school_id=_S1)],
        appearances=[make_appearance(student_id="a", media_id="m1", event_id="e1")],
        corrections=[
            make_match_correction(media_id="m1", student_id="a", verdict=MatchVerdict.CONFIRMED)
        ],
    )
    assert (
        await svc.download_url(school_id=_S1, media_id="m1", restrict_to_student_id="a")
    ).download_url


# ---- BP8b download audit (decisions/0050) ------------------------------
# Recording is a SEPARATE action (record_download) fired on the real download, NOT on the
# signed-URL mint (which is shared with viewing) — so a mere view is never audited.


async def test_download_url_mint_records_nothing() -> None:
    # A view/mint (any number of times) must NOT record a download.
    audit = FakeDownloadAuditRepo()
    svc = _svc(
        students=[make_student(id="a", school_id=_S1, user_id="ua")],
        media=[make_media(id="m1", school_id=_S1, event_id="e1")],
        appearances=[make_appearance(student_id="a", media_id="m1", event_id="e1")],
        audit=audit,
    )
    await svc.download_url(school_id=_S1, media_id="m1", restrict_to_student_id=None)
    await svc.download_url(school_id=_S1, media_id="m1", restrict_to_student_id="a")
    assert audit.rows == []


async def test_record_download_student_records_row_with_subject() -> None:
    audit = FakeDownloadAuditRepo()
    svc = _svc(
        students=[make_student(id="a", school_id=_S1, user_id="ua")],
        media=[make_media(id="m1", school_id=_S1, event_id="e1")],
        appearances=[make_appearance(student_id="a", media_id="m1", event_id="e1")],
        audit=audit,
    )
    await svc.record_download(
        school_id=_S1,
        media_id="m1",
        restrict_to_student_id="a",
        actor_user_id="ua",
        actor_role="student",
    )
    assert len(audit.rows) == 1
    row = audit.rows[0]
    assert row.media_id == "m1" and row.event_id == "e1"
    assert row.actor_user_id == "ua" and row.actor_role == "student"
    # A student self-download stamps the subject student; staff would leave it None.
    assert row.subject_student_id == "a"


async def test_record_download_staff_records_row_without_subject() -> None:
    audit = FakeDownloadAuditRepo()
    svc = _svc(
        media=[make_media(id="m1", school_id=_S1, event_id="e1")],
        audit=audit,
    )
    await svc.record_download(
        school_id=_S1,
        media_id="m1",
        restrict_to_student_id=None,
        actor_user_id="staff-1",
        actor_role="school_admin",
    )
    assert len(audit.rows) == 1
    assert audit.rows[0].subject_student_id is None


async def test_record_download_not_recorded_when_gate_denies() -> None:
    # A blocked download (student not appearing) 404s and records nothing.
    audit = FakeDownloadAuditRepo()
    svc = _svc(
        media=[make_media(id="m1", school_id=_S1, event_id="e1")],
        appearances=[],  # student "a" does not appear
        audit=audit,
    )
    with pytest.raises(NotFoundError):
        await svc.record_download(
            school_id=_S1,
            media_id="m1",
            restrict_to_student_id="a",
            actor_user_id="ua",
            actor_role="student",
        )
    assert audit.rows == []


async def test_record_download_missing_media_raises() -> None:
    audit = FakeDownloadAuditRepo()
    svc = _svc(media=[], audit=audit)
    with pytest.raises(NotFoundError):
        await svc.record_download(
            school_id=_S1,
            media_id="ghost",
            restrict_to_student_id=None,
            actor_user_id="staff-1",
            actor_role="school_admin",
        )
    assert audit.rows == []


async def test_student_media_hides_rejected_and_adds_missed() -> None:
    svc = _svc(
        students=[make_student(id="a", school_id=_S1, user_id="ua")],
        events=[make_event(id="e1", school_id=_S1)],
        media=[
            make_media(id="m1", school_id=_S1, event_id="e1"),
            make_media(id="m2", school_id=_S1, event_id="e1"),
            make_media(id="m3", school_id=_S1, event_id="e1"),
        ],
        appearances=[
            make_appearance(student_id="a", media_id="m1", event_id="e1"),
            make_appearance(student_id="a", media_id="m2", event_id="e1"),
        ],
        corrections=[
            make_match_correction(media_id="m2", student_id="a", verdict=MatchVerdict.REJECTED),
            make_match_correction(
                media_id="m3", student_id="a", event_id="e1", verdict=MatchVerdict.ADDED
            ),
        ],
    )
    media = await svc.student_media(school_id=_S1, student_id="a")
    assert {m.id for m in media} == {"m1", "m3"}  # m2 rejected out, m3 added in


async def test_event_students_media_count_is_effective() -> None:
    svc = _svc(
        students=[
            make_student(id="a", school_id=_S1, user_id="ua"),
            make_student(id="b", school_id=_S1, user_id="ub"),
        ],
        events=[make_event(id="e1", school_id=_S1)],
        appearances=[
            make_appearance(student_id="a", media_id="m1", event_id="e1"),
            make_appearance(student_id="a", media_id="m2", event_id="e1"),
            make_appearance(student_id="b", media_id="m1", event_id="e1"),
        ],
        corrections=[
            make_match_correction(
                media_id="m1", student_id="b", event_id="e1", verdict=MatchVerdict.REJECTED
            )
        ],
    )
    views = await svc.event_students(school_id=_S1, event_id="e1")
    counts = {v.student.id: v.media_count for v in views}
    assert counts == {"a": 2}  # b's only photo was rejected -> b drops out entirely


async def test_media_appearances_carries_verdict_and_added_has_null_confidence() -> None:
    svc = _svc(
        students=[
            make_student(id="a", school_id=_S1, user_id="ua"),
            make_student(id="b", school_id=_S1, user_id="ub"),
            make_student(id="c", school_id=_S1, user_id="uc"),
        ],
        media=[make_media(id="m1", school_id=_S1)],
        appearances=[
            make_appearance(
                student_id="a", media_id="m1", event_id="e1", confidence=0.9, needs_review=True
            ),
            make_appearance(student_id="c", media_id="m1", event_id="e1"),
        ],
        corrections=[
            make_match_correction(media_id="m1", student_id="a", verdict=MatchVerdict.CONFIRMED),
            make_match_correction(media_id="m1", student_id="b", verdict=MatchVerdict.ADDED),
            make_match_correction(media_id="m1", student_id="c", verdict=MatchVerdict.REJECTED),
        ],
    )
    apps = {ap.student.id: ap for ap in await svc.media_appearances(school_id=_S1, media_id="m1")}
    # The staff review surface shows ALL matches incl. rejected (with the verdict) so staff
    # can undo; only the student-facing reads hide rejected.
    assert set(apps) == {"a", "b", "c"}
    assert apps["a"].verdict is MatchVerdict.CONFIRMED and apps["a"].confidence == 0.9
    assert apps["b"].verdict is MatchVerdict.ADDED and apps["b"].confidence is None
    assert apps["c"].verdict is MatchVerdict.REJECTED


async def test_event_student_media_hides_rejected_and_adds_missed() -> None:
    # The per-student photo list inside an event applies the same overlay.
    svc = _svc(
        students=[make_student(id="a", school_id=_S1, user_id="ua")],
        events=[make_event(id="e1", school_id=_S1)],
        media=[
            make_media(id="m1", school_id=_S1, event_id="e1"),
            make_media(id="m2", school_id=_S1, event_id="e1"),
            make_media(id="m3", school_id=_S1, event_id="e1"),
        ],
        appearances=[
            make_appearance(student_id="a", media_id="m1", event_id="e1"),
            make_appearance(student_id="a", media_id="m2", event_id="e1"),
        ],
        corrections=[
            make_match_correction(
                media_id="m2", student_id="a", event_id="e1", verdict=MatchVerdict.REJECTED
            ),
            make_match_correction(
                media_id="m3", student_id="a", event_id="e1", verdict=MatchVerdict.ADDED
            ),
        ],
    )
    media = await svc.event_student_media(school_id=_S1, event_id="e1", student_id="a")
    assert {m.id for m in media} == {"m1", "m3"}  # m2 rejected out, m3 added in


async def test_student_events_drops_event_whose_only_photo_was_rejected() -> None:
    # A student's event rollup: an event drops entirely once its sole photo for the
    # student is rejected; its effective media_count reflects the overlay.
    svc = _svc(
        students=[make_student(id="a", school_id=_S1, user_id="ua")],
        events=[
            make_event(id="e1", school_id=_S1),
            make_event(id="e2", school_id=_S1),
        ],
        appearances=[
            make_appearance(student_id="a", media_id="m1", event_id="e1"),
            make_appearance(student_id="a", media_id="m2", event_id="e2"),
        ],
        corrections=[
            make_match_correction(
                media_id="m2", student_id="a", event_id="e2", verdict=MatchVerdict.REJECTED
            )
        ],
    )
    views = await svc.student_events(school_id=_S1, student_id="a")
    rollups = {v.event.id: v.media_count for v in views}
    assert rollups == {"e1": 1}  # e2 gone — its only photo for a was rejected
