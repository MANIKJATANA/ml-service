"""AuditService reads — the download audit's two surfaces (BP8b, decisions/0050).

Covers display composition (actor email, event/student names), the per-photo count + 404,
tenant scoping, pagination + event/student filters, and the graceful degradation when the
actor/subject account was later deleted (id reads None; the denormalized role stays).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from backend.domain.errors import NotFoundError
from backend.domain.models import (
    DownloadAuditEntry,
    Event,
    Media,
    Role,
    Student,
    User,
)
from backend.services.audit_service import AuditService
from backend_fakes import (
    FakeDownloadAuditRepo,
    FakeEventRepo,
    FakeMediaRepo,
    FakeStudentRepo,
    FakeUserRepo,
    make_download_audit_entry,
    make_event,
    make_media,
    make_student,
    make_user,
)

_S1 = "s1"


def _t(second: int) -> datetime:
    return datetime(2026, 1, 1, 0, 0, second, tzinfo=UTC)


def _svc(
    *,
    entries: list[DownloadAuditEntry] | None = None,
    users: list[User] | None = None,
    events: list[Event] | None = None,
    students: list[Student] | None = None,
    media: list[Media] | None = None,
) -> AuditService:
    return AuditService(
        FakeDownloadAuditRepo(entries or []),
        FakeMediaRepo(media or []),
        FakeEventRepo(events or []),
        FakeStudentRepo(students or []),
        FakeUserRepo(users or []),
    )


# ---- per-photo history -------------------------------------------------


async def test_media_history_composes_and_counts_newest_first() -> None:
    svc = _svc(
        media=[make_media(id="m1", school_id=_S1, event_id="e1")],
        events=[make_event(id="e1", school_id=_S1, name="Sports Day")],
        students=[make_student(id="a", school_id=_S1, user_id="ua", name="Ann")],
        users=[
            make_user(id="staff", school_id=_S1, email="sa@x.io", role=Role.SCHOOL_ADMIN),
            make_user(id="ua", school_id=_S1, email="ann@x.io", role=Role.STUDENT),
        ],
        entries=[
            make_download_audit_entry(
                id="a1", school_id=_S1, media_id="m1", event_id="e1",
                actor_user_id="staff", actor_role="school_admin",
                subject_student_id=None, created_at=_t(1),
            ),
            make_download_audit_entry(
                id="a2", school_id=_S1, media_id="m1", event_id="e1",
                actor_user_id="ua", actor_role="student",
                subject_student_id="a", created_at=_t(2),
            ),
        ],
    )
    hist = await svc.media_download_history(school_id=_S1, media_id="m1")
    assert hist.count == 2
    assert [e.id for e in hist.entries] == ["a2", "a1"]  # newest-first
    latest = hist.entries[0]
    assert latest.actor_email == "ann@x.io"
    assert latest.actor_role == "student"
    assert latest.subject_student_name == "Ann"
    assert latest.event_name == "Sports Day"
    # A staff download carries no subject student.
    assert hist.entries[1].subject_student_id is None
    assert hist.entries[1].subject_student_name is None


async def test_media_history_missing_media_raises() -> None:
    svc = _svc(media=[])
    with pytest.raises(NotFoundError):
        await svc.media_download_history(school_id=_S1, media_id="ghost")


async def test_media_history_tenant_scoped() -> None:
    # Media exists but in another school -> 404 (never confirms its existence).
    svc = _svc(media=[make_media(id="m1", school_id=_S1, event_id="e1")])
    with pytest.raises(NotFoundError):
        await svc.media_download_history(school_id="other", media_id="m1")


async def test_media_history_only_that_media() -> None:
    svc = _svc(
        media=[make_media(id="m1", school_id=_S1, event_id="e1")],
        events=[make_event(id="e1", school_id=_S1)],
        users=[make_user(id="u", school_id=_S1, role=Role.SCHOOL_ADMIN)],
        entries=[
            make_download_audit_entry(
                id="a1", school_id=_S1, media_id="m1", event_id="e1", actor_user_id="u"
            ),
            make_download_audit_entry(
                id="a2", school_id=_S1, media_id="m2", event_id="e1", actor_user_id="u"
            ),
        ],
    )
    hist = await svc.media_download_history(school_id=_S1, media_id="m1")
    assert hist.count == 1 and [e.id for e in hist.entries] == ["a1"]


# ---- school-wide log ---------------------------------------------------


def _log_svc() -> AuditService:
    return _svc(
        media=[make_media(id="m1", school_id=_S1, event_id="e1")],
        events=[
            make_event(id="e1", school_id=_S1, name="Sports Day"),
            make_event(id="e2", school_id=_S1, name="Recital"),
        ],
        students=[make_student(id="a", school_id=_S1, user_id="ua", name="Ann")],
        users=[make_user(id="staff", school_id=_S1, email="sa@x.io", role=Role.SCHOOL_ADMIN)],
        entries=[
            make_download_audit_entry(
                id=f"a{n}", school_id=_S1, media_id="m1",
                event_id="e1" if n % 2 else "e2",
                actor_user_id="staff", actor_role="school_admin",
                subject_student_id="a" if n == 1 else None,
                created_at=_t(n),
            )
            for n in range(1, 6)  # a1..a5
        ],
    )


async def test_log_paginates_newest_first() -> None:
    svc = _log_svc()
    page = await svc.school_download_log(school_id=_S1, limit=2, offset=0)
    assert page.total == 5 and page.limit == 2 and page.offset == 0
    assert [i.id for i in page.items] == ["a5", "a4"]
    page2 = await svc.school_download_log(school_id=_S1, limit=2, offset=2)
    assert [i.id for i in page2.items] == ["a3", "a2"]


async def test_log_filters_by_event() -> None:
    svc = _log_svc()
    page = await svc.school_download_log(school_id=_S1, limit=50, offset=0, event_id="e2")
    # a2, a4 are e2 (even n).
    assert page.total == 2 and {i.id for i in page.items} == {"a2", "a4"}
    assert all(i.event_name == "Recital" for i in page.items)


async def test_log_filters_by_student() -> None:
    svc = _log_svc()
    page = await svc.school_download_log(
        school_id=_S1, limit=50, offset=0, student_id="a"
    )
    assert page.total == 1 and [i.id for i in page.items] == ["a1"]
    assert page.items[0].subject_student_name == "Ann"


async def test_log_tenant_scoped_excludes_foreign_rows() -> None:
    svc = _svc(
        media=[make_media(id="m1", school_id=_S1, event_id="e1")],
        events=[make_event(id="e1", school_id=_S1)],
        users=[make_user(id="u", school_id=_S1, role=Role.SCHOOL_ADMIN)],
        entries=[
            make_download_audit_entry(
                id="mine", school_id=_S1, media_id="m1", event_id="e1", actor_user_id="u"
            ),
            make_download_audit_entry(
                id="theirs", school_id="other", media_id="mx", event_id="ex",
                actor_user_id="u",
            ),
        ],
    )
    page = await svc.school_download_log(school_id=_S1, limit=50, offset=0)
    assert [i.id for i in page.items] == ["mine"]


async def test_log_deleted_actor_and_subject_degrade_gracefully() -> None:
    # actor_user_id / subject_student_id read None (FK SET NULL); the role still shows.
    svc = _svc(
        media=[make_media(id="m1", school_id=_S1, event_id="e1")],
        events=[make_event(id="e1", school_id=_S1)],
        students=[],  # subject student gone
        users=[],  # actor gone
        entries=[
            make_download_audit_entry(
                id="a1", school_id=_S1, media_id="m1", event_id="e1",
                actor_user_id=None, actor_role="student", subject_student_id="gone",
            ),
        ],
    )
    page = await svc.school_download_log(school_id=_S1, limit=50, offset=0)
    item = page.items[0]
    assert item.actor_user_id is None and item.actor_email is None
    assert item.actor_role == "student"  # denormalized, survives the deletion
    assert item.subject_student_name is None
