"""Gated Postgres repository tests (real DB required).

Run with a live Postgres, e.g.::

    BE_TEST_DATABASE_URL=postgresql+asyncpg://app:app@localhost:5432/app \
        uv run pytest services/backend/tests/adapters

Skipped otherwise (like the ML service's gated PG tests), so the default gate stays
green without a database. The schema is built with ``create_all`` (a test-only use
of the metadata, per working rule 0007); production schema comes from migration 0001.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import pytest
from backend.adapters.repositories.postgres_download_audit import (
    PostgresDownloadAuditRepository,
)
from backend.adapters.repositories.postgres_event_categories import (
    PostgresEventCategoryRepository,
)
from backend.adapters.repositories.postgres_events import PostgresEventRepository
from backend.adapters.repositories.postgres_match_corrections import (
    PostgresMatchCorrectionRepository,
)
from backend.adapters.repositories.postgres_media import PostgresMediaRepository
from backend.adapters.repositories.postgres_notification_reads import (
    PostgresNotificationReadRepository,
)
from backend.adapters.repositories.postgres_schools import PostgresSchoolRepository
from backend.adapters.repositories.postgres_student_groups import (
    PostgresStudentGroupRepository,
)
from backend.adapters.repositories.postgres_students import PostgresStudentRepository
from backend.adapters.repositories.postgres_teacher_classes import (
    PostgresTeacherClassRepository,
)
from backend.adapters.repositories.postgres_users import PostgresUserRepository
from backend.db.base import Base
from backend.db.session import make_engine, make_sessionmaker
from backend.domain.errors import ConflictError, NotFoundError
from backend.domain.models import (
    EnrollmentFailureReason,
    EnrollmentStatus,
    EventProcessingStatus,
    EventStatus,
    MatchVerdict,
    MediaProcessingStatus,
    MediaType,
    Role,
    StudentSort,
    UserSort,
    UserStatus,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_DSN = os.environ.get("BE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(_DSN is None, reason="BE_TEST_DATABASE_URL not set")

# A well-formed UUID that never exists — for "valid id, absent row" assertions.
_MISSING_UUID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
async def sm() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    assert _DSN is not None
    engine = make_engine(_DSN)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield make_sessionmaker(engine)
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def test_school_create_get_list(sm: async_sessionmaker[AsyncSession]) -> None:
    repo = PostgresSchoolRepository(sm)
    created = await repo.create(name="Springfield Elementary", max_teachers=5)
    assert created.id and created.name == "Springfield Elementary"
    assert created.max_teachers == 5
    assert created.status.value == "active"

    got = await repo.get(created.id)
    assert got is not None and got.id == created.id
    assert await repo.get("not-a-uuid") is None  # malformed -> None, not an error

    listed = await repo.list_all()
    assert [s.id for s in listed] == [created.id]


async def test_user_create_get_by_email_and_conflict(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    school = await schools.create(name="Springfield Elementary", max_teachers=5)

    admin = await users.create(
        school_id=None, email="admin@x.io", password_hash="h", role=Role.PLATFORM_ADMIN
    )
    assert admin.school_id is None and admin.role is Role.PLATFORM_ADMIN

    teacher = await users.create(
        school_id=school.id, email="t@x.io", password_hash="h", role=Role.TEACHER
    )
    assert teacher.school_id == school.id

    fetched = await users.get_by_email("t@x.io")
    assert fetched is not None and fetched.id == teacher.id
    assert await users.get_by_email("missing@x.io") is None

    # Email is a case-insensitive identifier: lookup is case-insensitive and a
    # case-variant duplicate still conflicts (decisions/0024).
    assert (await users.get_by_email("T@X.IO")) is not None
    with pytest.raises(ConflictError):
        await users.create(
            school_id=school.id, email="T@X.io", password_hash="h", role=Role.TEACHER
        )

    with pytest.raises(ConflictError):
        await users.create(
            school_id=school.id, email="t@x.io", password_hash="h", role=Role.TEACHER
        )


async def test_user_must_change_password_and_set_password(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    school = await schools.create(name="Springfield Elementary", max_teachers=5)

    # Default is False; a temp-password account is provisioned True.
    normal = await users.create(
        school_id=school.id, email="a@x.io", password_hash="h1", role=Role.TEACHER
    )
    assert normal.must_change_password is False
    temp = await users.create(
        school_id=school.id,
        email="b@x.io",
        password_hash="h2",
        role=Role.STUDENT,
        must_change_password=True,
    )
    assert temp.must_change_password is True

    # set_password rewrites the hash and clears the flag.
    assert temp.token_version == 0  # a fresh account starts at 0 (server default)
    await users.set_password(temp.id, password_hash="h2-new", must_change_password=False)
    reloaded = await users.get(temp.id)
    assert reloaded is not None
    assert reloaded.password_hash == "h2-new"
    assert reloaded.must_change_password is False

    # BP18d: a password change bumps token_version (revoking previously-issued tokens);
    # a transparent rehash-on-login (revoke_sessions=False) does NOT — else the token just
    # issued at that same login would be invalidated instantly.
    assert reloaded.token_version == temp.token_version + 1
    await users.set_password(
        temp.id,
        password_hash="h2-rehash",
        must_change_password=False,
        revoke_sessions=False,
    )
    rehashed = await users.get(temp.id)
    assert rehashed is not None
    assert rehashed.password_hash == "h2-rehash"
    assert rehashed.token_version == reloaded.token_version  # unchanged by a rehash

    # A missing user is a NotFoundError, not a silent no-op.
    with pytest.raises(NotFoundError):
        await users.set_password(
            "00000000-0000-0000-0000-000000000000",
            password_hash="x",
            must_change_password=False,
        )


async def test_user_set_status_disables_and_reenables(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    # BP7c: set_status flips users.status (which auth checks) and round-trips.
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    school = await schools.create(name="S", max_teachers=5)
    u = await users.create(
        school_id=school.id, email="t@x.io", password_hash="h", role=Role.TEACHER
    )
    assert u.status is UserStatus.ACTIVE  # default

    await users.set_status(u.id, status=UserStatus.DISABLED)
    disabled = await users.get(u.id)
    assert disabled is not None and disabled.status is UserStatus.DISABLED

    await users.set_status(u.id, status=UserStatus.ACTIVE)
    enabled = await users.get(u.id)
    assert enabled is not None and enabled.status is UserStatus.ACTIVE

    with pytest.raises(NotFoundError):
        await users.set_status(
            "00000000-0000-0000-0000-000000000000", status=UserStatus.DISABLED
        )


async def test_count_and_list_by_school_and_role(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    b = await schools.create(name="B", max_teachers=5)

    await users.create(
        school_id=a.id, email="admin@a.io", password_hash="h", role=Role.SCHOOL_ADMIN
    )
    await users.create(
        school_id=a.id, email="t1@a.io", password_hash="h", role=Role.TEACHER
    )
    await users.create(
        school_id=a.id, email="t2@a.io", password_hash="h", role=Role.TEACHER
    )
    await users.create(
        school_id=b.id, email="t@b.io", password_hash="h", role=Role.TEACHER
    )

    # Scoped to one school + role; the admin is not counted as a teacher.
    assert await users.count_by_school_and_role(a.id, Role.TEACHER) == 2
    assert await users.count_by_school_and_role(a.id, Role.SCHOOL_ADMIN) == 1
    assert await users.count_by_school_and_role(b.id, Role.TEACHER) == 1
    assert await users.count_by_school_and_role("not-a-uuid", Role.TEACHER) == 0

    listed = await users.list_by_school_and_role(a.id, Role.TEACHER)
    assert {u.email for u in listed} == {"t1@a.io", "t2@a.io"}
    assert await users.list_by_school_and_role("not-a-uuid", Role.TEACHER) == []


# ---- events + media (Phase 5, decisions/0027) -------------------------


async def test_event_create_get_list_update_and_processing(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    schools = PostgresSchoolRepository(sm)
    events = PostgresEventRepository(sm)
    school = await schools.create(name="A", max_teachers=5)

    ev = await events.create(
        school_id=school.id, name="Sports Day", description=None,
        event_date=None, created_by=None,
    )
    assert ev.status is EventStatus.ACTIVE
    assert ev.processing_status is EventProcessingStatus.NOT_STARTED

    got = await events.get(school.id, ev.id)
    assert got is not None and got.id == ev.id
    assert await events.get("other-school-not-uuid", ev.id) is None  # tenant-safe

    listed = await events.list_by_school(school.id)
    assert [e.id for e in listed] == [ev.id]

    renamed = await events.update(school.id, ev.id, name="Renamed",
                                  status=EventStatus.ARCHIVED)
    assert renamed is not None and renamed.name == "Renamed"
    assert renamed.status is EventStatus.ARCHIVED

    # set_processing stamps enqueued_at on queued (the only status the backend sets).
    await events.set_processing(ev.id, status=EventProcessingStatus.QUEUED)
    queued = await events.get(school.id, ev.id)
    assert queued is not None and queued.enqueued_at is not None
    assert queued.processing_status is EventProcessingStatus.QUEUED


async def test_media_create_list_and_counts(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    schools = PostgresSchoolRepository(sm)
    events = PostgresEventRepository(sm)
    media = PostgresMediaRepository(sm)
    school = await schools.create(name="A", max_teachers=5)
    ev = await events.create(
        school_id=school.id, name="E", description=None, event_date=None,
        created_by=None,
    )

    m1 = await media.create(
        school_id=school.id, event_id=ev.id, storage_path="events/a/e/p1.jpg",
        media_type=MediaType.IMAGE,
    )
    await media.create(
        school_id=school.id, event_id=ev.id, storage_path="events/a/e/p2.mp4",
        media_type=MediaType.VIDEO,
    )
    # Recorded pending; the ML worker (not this repo) later flips the status column.
    assert m1.processing_status is MediaProcessingStatus.PENDING

    got = await media.get(school.id, m1.id)
    assert got is not None and got.media_type is MediaType.IMAGE
    assert await media.get("not-a-uuid", m1.id) is None  # tenant-safe

    assert len(await media.list_by_event(school.id, ev.id)) == 2
    counts = await media.status_counts(school.id, ev.id)
    assert counts[MediaProcessingStatus.PENDING] == 2


async def test_media_and_student_thumbnail_paths_round_trip(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    # BP17: the backend-generated thumbnail path persists (media) + is nullable (a video / a
    # pre-BP17 photo with no thumb round-trips as NULL), and the student reference-photo
    # thumbnail sibling round-trips through create + set_reference_photo. (Paths use the
    # shipped ``thumb-{name}.jpg`` convention the backend actually writes.)
    schools = PostgresSchoolRepository(sm)
    events = PostgresEventRepository(sm)
    users = PostgresUserRepository(sm)
    media = PostgresMediaRepository(sm)
    students = PostgresStudentRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    ev = await events.create(
        school_id=a.id, name="E", description=None, event_date=None, created_by=None
    )

    with_thumb = await media.create(
        school_id=a.id, event_id=ev.id, storage_path="events/a/e/p.jpg",
        media_type=MediaType.IMAGE, thumbnail_path="events/a/e/thumb-p.jpg",
    )
    no_thumb = await media.create(
        school_id=a.id, event_id=ev.id, storage_path="events/a/e/clip.mp4",
        media_type=MediaType.VIDEO,  # thumbnail_path defaults to None
    )
    got = await media.get(a.id, with_thumb.id)
    assert got is not None and got.thumbnail_path == "events/a/e/thumb-p.jpg"
    got_none = await media.get(a.id, no_thumb.id)
    assert got_none is not None and got_none.thumbnail_path is None

    login = await users.create(
        school_id=a.id, email="s@a.io", password_hash="h", role=Role.STUDENT
    )
    s = await students.create(
        school_id=a.id, user_id=login.id, name="S",
        reference_photo_path="reference-photos/a/p.jpg",
        reference_photo_thumbnail_path="reference-photos/a/thumb-p.jpg",
    )
    fetched = await students.get(a.id, s.id)
    assert fetched is not None
    assert fetched.reference_photo_thumbnail_path == "reference-photos/a/thumb-p.jpg"

    # Replacing the photo swaps the thumbnail sibling in lockstep (BP7d-2 + BP17).
    await students.set_reference_photo(
        s.id, reference_photo_path="reference-photos/a/new.jpg",
        reference_photo_thumbnail_path="reference-photos/a/thumb-new.jpg",
    )
    updated = await students.get(a.id, s.id)
    assert updated is not None
    assert updated.reference_photo_path == "reference-photos/a/new.jpg"
    assert updated.reference_photo_thumbnail_path == "reference-photos/a/thumb-new.jpg"


async def test_media_list_by_ids_is_tenant_scoped_and_defensive(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    schools = PostgresSchoolRepository(sm)
    events = PostgresEventRepository(sm)
    media = PostgresMediaRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    b = await schools.create(name="B", max_teachers=5)
    ea = await events.create(
        school_id=a.id, name="EA", description=None, event_date=None, created_by=None
    )
    eb = await events.create(
        school_id=b.id, name="EB", description=None, event_date=None, created_by=None
    )
    m1 = await media.create(
        school_id=a.id, event_id=ea.id, storage_path="events/a/e/1.jpg",
        media_type=MediaType.IMAGE,
    )
    m2 = await media.create(
        school_id=a.id, event_id=ea.id, storage_path="events/a/e/2.jpg",
        media_type=MediaType.IMAGE,
    )
    other = await media.create(
        school_id=b.id, event_id=eb.id, storage_path="events/b/e/3.jpg",
        media_type=MediaType.IMAGE,
    )

    # Only this tenant's ids come back; a foreign id and a garbage id are dropped.
    got = await media.list_by_ids(
        a.id, [m1.id, m2.id, other.id, "not-a-uuid", str(_MISSING_UUID)]
    )
    assert {m.id for m in got} == {m1.id, m2.id}
    assert await media.list_by_ids(a.id, []) == []


# ---- BP1 dashboard aggregates (decisions/0038) ------------------------


async def test_student_enrollment_counts_is_tenant_scoped(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    students = PostgresStudentRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    b = await schools.create(name="B", max_teachers=5)

    async def add(school_id: str, email: str, status: EnrollmentStatus) -> None:
        login = await users.create(
            school_id=school_id, email=email, password_hash="h", role=Role.STUDENT
        )
        s = await students.create(
            school_id=school_id, user_id=login.id, name="N",
            reference_photo_path="p",
        )
        if status is not EnrollmentStatus.PENDING:  # create defaults to pending
            await students.set_enrollment(s.id, status=status)

    await add(a.id, "s1@a.io", EnrollmentStatus.ENROLLED)
    await add(a.id, "s2@a.io", EnrollmentStatus.ENROLLED)
    await add(a.id, "s3@a.io", EnrollmentStatus.PENDING)
    await add(a.id, "s4@a.io", EnrollmentStatus.FAILED)
    await add(b.id, "s5@b.io", EnrollmentStatus.ENROLLED)  # other school — noise

    counts = await students.enrollment_counts(a.id)
    assert counts[EnrollmentStatus.ENROLLED] == 2  # B's enrolled student excluded
    assert counts[EnrollmentStatus.PENDING] == 1
    assert counts[EnrollmentStatus.FAILED] == 1
    # Zero-filled + tenant-safe on a malformed id.
    assert await students.enrollment_counts("not-a-uuid") == {
        s: 0 for s in EnrollmentStatus
    }


async def test_set_enrollment_persists_and_clears_failure_reason(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    # BP7b: the reason round-trips through the column (+ its CHECK), reads back via
    # _to_student, and is cleared to NULL on a subsequent success.
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    students = PostgresStudentRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    login = await users.create(
        school_id=a.id, email="s@a.io", password_hash="h", role=Role.STUDENT
    )
    s = await students.create(
        school_id=a.id, user_id=login.id, name="N", reference_photo_path="p",
    )
    fresh = await students.get(a.id, s.id)
    assert fresh is not None and fresh.enrollment_failure_reason is None

    await students.set_enrollment(
        s.id, status=EnrollmentStatus.FAILED,
        failure_reason=EnrollmentFailureReason.NO_FACE,
    )
    failed = await students.get(a.id, s.id)
    assert failed is not None
    assert failed.enrollment_status is EnrollmentStatus.FAILED
    assert failed.enrollment_failure_reason is EnrollmentFailureReason.NO_FACE

    # A subsequent success (no reason passed) clears it.
    await students.set_enrollment(s.id, status=EnrollmentStatus.ENROLLED)
    ok = await students.get(a.id, s.id)
    assert ok is not None
    assert ok.enrollment_status is EnrollmentStatus.ENROLLED
    assert ok.enrollment_failure_reason is None


async def test_student_create_without_a_reference_photo(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    # BP7d: a bulk-imported student is created photoless (reference_photo_path NULL) and
    # round-trips through the now-nullable column as pending.
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    students = PostgresStudentRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    login = await users.create(
        school_id=a.id, email="np@a.io", password_hash="h", role=Role.STUDENT
    )
    s = await students.create(school_id=a.id, user_id=login.id, name="No Photo")
    assert s.reference_photo_path is None
    got = await students.get(a.id, s.id)
    assert got is not None
    assert got.reference_photo_path is None
    assert got.enrollment_status is EnrollmentStatus.PENDING

    # BP7d-2: set_reference_photo fills in the path (round-trips through the column).
    await students.set_reference_photo(s.id, reference_photo_path="reference-photos/a/p.jpg")
    withphoto = await students.get(a.id, s.id)
    assert withphoto is not None
    assert withphoto.reference_photo_path == "reference-photos/a/p.jpg"


async def test_event_status_counts_and_undistributed_alert(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    schools = PostgresSchoolRepository(sm)
    events = PostgresEventRepository(sm)
    media = PostgresMediaRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    b = await schools.create(name="B", max_teachers=5)

    async def mk(school_id: str, name: str) -> str:
        ev = await events.create(
            school_id=school_id, name=name, description=None, event_date=None,
            created_by=None,
        )
        return ev.id

    e1 = await mk(a.id, "not_started+media")  # active, not_started, has pending media
    await mk(a.id, "not_started, no media")  # active, not_started, no media
    e3 = await mk(a.id, "processing")  # active, processing, has media
    e4 = await mk(a.id, "archived+completed")  # archived, completed
    e5 = await mk(a.id, "archived not_started+media")  # archived, not_started, has media
    e6 = await mk(a.id, "completed+second-batch")  # active, completed, has NEW pending media
    await mk(b.id, "B-noise")  # other school

    await events.set_processing(e3, status=EventProcessingStatus.PROCESSING)
    await events.update(a.id, e4, status=EventStatus.ARCHIVED)
    await events.set_processing(e4, status=EventProcessingStatus.COMPLETED)
    await events.update(a.id, e5, status=EventStatus.ARCHIVED)
    await events.set_processing(e6, status=EventProcessingStatus.COMPLETED)

    for ev_id, path in ((e1, "p1.jpg"), (e3, "p3.jpg"), (e5, "p5.jpg"), (e6, "p6.jpg")):
        await media.create(
            school_id=a.id, event_id=ev_id, storage_path=path,
            media_type=MediaType.IMAGE,
        )  # media.create defaults to processing_status='pending'

    rollup = await events.status_counts(a.id)
    # 6 events: e1/e2/e3/e6 active, e4/e5 archived; only e3 in-flight.
    assert (rollup.total, rollup.active, rollup.archived, rollup.processing) == (
        6, 4, 2, 1,
    )

    # BP19c: active, not-in-flight events with >=1 PENDING photo. e1 (not_started+pending)
    # AND e6 (completed but a NEW pending batch — the widening) both count. e3 is in-flight;
    # e5 is archived; e2 has no media → all excluded.
    assert await events.count_active_with_pending_media(a.id) == 2
    assert await events.count_active_with_pending_media("not-a-uuid") == 0

    # BP19c: pending photos per event (status-agnostic — every event with pending media
    # appears; the list derives the pill, the alert filters by event status). All four created
    # media are pending, so e1/e3/e5/e6 each read 1 (the no-media event is absent).
    pending_by_event = await media.pending_counts_by_event(a.id)
    assert pending_by_event.get(e1) == 1 and pending_by_event.get(e6) == 1
    assert set(pending_by_event) == {e1, e3, e5, e6}

    # count_distributed (BP7a): "announced" = a manual notified_at OR (auto_notify —
    # server-defaults true — AND completed_at). e4 (ARCHIVED + completed) and e6 (completed)
    # are both announced via the auto path (distribution is status-agnostic); mark e1 notified
    # too. e2/e3/e5 are neither completed nor notified -> excluded.
    await events.mark_notified(e1)
    assert await events.count_distributed(a.id) == 3
    assert await events.count_distributed(b.id) == 0
    assert await events.count_distributed("not-a-uuid") == 0


async def test_media_school_status_counts_is_tenant_scoped(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    schools = PostgresSchoolRepository(sm)
    events = PostgresEventRepository(sm)
    media = PostgresMediaRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    b = await schools.create(name="B", max_teachers=5)
    ea = await events.create(
        school_id=a.id, name="EA", description=None, event_date=None, created_by=None
    )
    eb = await events.create(
        school_id=b.id, name="EB", description=None, event_date=None, created_by=None
    )
    await media.create(
        school_id=a.id, event_id=ea.id, storage_path="a1.jpg", media_type=MediaType.IMAGE
    )
    await media.create(
        school_id=a.id, event_id=ea.id, storage_path="a2.mp4", media_type=MediaType.VIDEO
    )
    await media.create(
        school_id=b.id, event_id=eb.id, storage_path="b1.jpg", media_type=MediaType.IMAGE
    )  # other school — noise

    counts = await media.school_status_counts(a.id)
    assert counts[MediaProcessingStatus.PENDING] == 2  # recorded pending
    assert sum(counts.values()) == 2  # tenant-scoped total (B excluded)
    assert await media.school_status_counts("not-a-uuid") == {
        s: 0 for s in MediaProcessingStatus
    }


async def test_bp2_platform_and_event_rollups(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    students = PostgresStudentRepository(sm)
    events = PostgresEventRepository(sm)
    media = PostgresMediaRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    b = await schools.create(name="B", max_teachers=5)

    # A: 1 admin + 2 teachers; B: 1 admin; + a platform admin (null school → excluded).
    await users.create(
        school_id=None, email="pa@x.io", password_hash="h", role=Role.PLATFORM_ADMIN
    )
    await users.create(
        school_id=a.id, email="ad@a.io", password_hash="h", role=Role.SCHOOL_ADMIN
    )
    await users.create(
        school_id=a.id, email="t1@a.io", password_hash="h", role=Role.TEACHER
    )
    await users.create(
        school_id=a.id, email="t2@a.io", password_hash="h", role=Role.TEACHER
    )
    await users.create(
        school_id=b.id, email="ad@b.io", password_hash="h", role=Role.SCHOOL_ADMIN
    )
    # Students: 2 in A, 1 in B (each needs a login user).
    for i, sid in enumerate((a.id, a.id, b.id)):
        login = await users.create(
            school_id=sid, email=f"s{i}@x.io", password_hash="h", role=Role.STUDENT
        )
        await students.create(
            school_id=sid, user_id=login.id, name="N", reference_photo_path="p"
        )
    ea = await events.create(
        school_id=a.id, name="E", description=None, event_date=None, created_by=None
    )
    await media.create(
        school_id=a.id, event_id=ea.id, storage_path="p1", media_type=MediaType.IMAGE
    )
    await media.create(
        school_id=a.id, event_id=ea.id, storage_path="p2", media_type=MediaType.IMAGE
    )

    role_counts = await users.role_counts_by_school()
    assert role_counts[a.id][Role.SCHOOL_ADMIN] == 1
    assert role_counts[a.id][Role.TEACHER] == 2
    assert role_counts[b.id][Role.SCHOOL_ADMIN] == 1
    assert set(role_counts) == {a.id, b.id}  # platform admin (null school) excluded

    assert await students.counts_by_school() == {a.id: 2, b.id: 1}
    assert await events.counts_by_school() == {a.id: 1}
    assert await media.counts_by_event(a.id) == {ea.id: 2}
    assert await media.counts_by_event("not-a-uuid") == {}


# ---- BP4 distribution (decisions/0041) --------------------------------


async def test_set_processing_keeps_completed_at_on_requeue(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    schools = PostgresSchoolRepository(sm)
    events = PostgresEventRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    ev = await events.create(
        school_id=a.id, name="E", description=None, event_date=None, created_by=None
    )
    assert ev.auto_notify is True and ev.notified_at is None  # migration defaults

    await events.set_processing(ev.id, status=EventProcessingStatus.COMPLETED)
    done = await events.get(a.id, ev.id)
    assert done is not None and done.completed_at is not None

    # Redistribute (QUEUED) must NOT clear completed_at (BP4 set-forward — decisions/0041).
    await events.set_processing(ev.id, status=EventProcessingStatus.QUEUED)
    requeued = await events.get(a.id, ev.id)
    assert requeued is not None
    assert requeued.processing_status is EventProcessingStatus.QUEUED
    assert requeued.completed_at is not None

    # mark_notified stamps notified_at; auto toggle via update.
    await events.mark_notified(ev.id)
    notified = await events.get(a.id, ev.id)
    assert notified is not None and notified.notified_at is not None
    toggled = await events.update(a.id, ev.id, auto_notify=False)
    assert toggled is not None and toggled.auto_notify is False


async def test_notification_reads_upsert_and_scope(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    students = PostgresStudentRepository(sm)
    events = PostgresEventRepository(sm)
    reads = PostgresNotificationReadRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    login = await users.create(
        school_id=a.id, email="s@x.io", password_hash="h", role=Role.STUDENT
    )
    student = await students.create(
        school_id=a.id, user_id=login.id, name="N", reference_photo_path="p"
    )
    ev = await events.create(
        school_id=a.id, name="E", description=None, event_date=None, created_by=None
    )

    assert await reads.list_for_student(a.id, student.id) == {}
    await reads.mark_seen(school_id=a.id, student_id=student.id, event_id=ev.id)
    first = await reads.list_for_student(a.id, student.id)
    assert set(first) == {ev.id}

    # Upsert on the (student, event) natural key — no duplicate, seen_at moves forward.
    await reads.mark_seen(school_id=a.id, student_id=student.id, event_id=ev.id)
    again = await reads.list_for_student(a.id, student.id)
    assert set(again) == {ev.id}
    assert again[ev.id] >= first[ev.id]

    # Event-side lookup (the staff roster) + tenant-safe on a malformed id.
    assert set(await reads.list_for_event(a.id, ev.id)) == {student.id}
    assert await reads.list_for_student("not-a-uuid", student.id) == {}
    assert await reads.list_for_event("not-a-uuid", ev.id) == {}


async def test_match_corrections_upsert_get_delete_list_and_scope(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    students = PostgresStudentRepository(sm)
    events = PostgresEventRepository(sm)
    media = PostgresMediaRepository(sm)
    corr = PostgresMatchCorrectionRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    login = await users.create(
        school_id=a.id, email="s@x.io", password_hash="h", role=Role.STUDENT
    )
    student = await students.create(
        school_id=a.id, user_id=login.id, name="N", reference_photo_path="p"
    )
    staff = await users.create(
        school_id=a.id, email="t@x.io", password_hash="h", role=Role.TEACHER
    )
    ev = await events.create(
        school_id=a.id, name="E", description=None, event_date=None, created_by=None
    )
    m = await media.create(
        school_id=a.id, event_id=ev.id, storage_path="p1.jpg", media_type=MediaType.IMAGE
    )

    assert await corr.get(a.id, m.id, student.id) is None
    await corr.upsert(
        school_id=a.id, media_id=m.id, student_id=student.id, event_id=ev.id,
        verdict=MatchVerdict.REJECTED, corrected_by=staff.id, reason="x",
        resolves_review=True,
    )
    got = await corr.get(a.id, m.id, student.id)
    assert got is not None
    assert got.verdict is MatchVerdict.REJECTED and got.resolves_review is True
    assert await corr.count_resolved(a.id) == 1

    # Upsert on the (media, student) natural key — latest verdict wins, no duplicate.
    await corr.upsert(
        school_id=a.id, media_id=m.id, student_id=student.id, event_id=ev.id,
        verdict=MatchVerdict.CONFIRMED, corrected_by=staff.id, reason=None,
        resolves_review=False,
    )
    again = await corr.get(a.id, m.id, student.id)
    assert again is not None and again.verdict is MatchVerdict.CONFIRMED
    assert await corr.count_resolved(a.id) == 0  # resolves_review flipped off

    assert {c.student_id for c in await corr.list_for_media(a.id, m.id)} == {student.id}
    assert {c.media_id for c in await corr.list_for_event(a.id, ev.id)} == {m.id}
    assert {c.media_id for c in await corr.list_for_student(a.id, student.id)} == {m.id}
    assert await corr.list_for_media("not-a-uuid", m.id) == []  # tenant-safe

    await corr.delete(a.id, m.id, student.id)
    assert await corr.get(a.id, m.id, student.id) is None


async def test_student_erasure_cascades_and_anonymizes(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    # BP8e (decisions/0053): deleting a student's login cascades the profile +
    # notification_reads + the student's match_corrections away (two-level FK cascade
    # users -> students -> {...}); download_audit rows survive with the student/actor NULLed.
    # A second student's data must be untouched.
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    students = PostgresStudentRepository(sm)
    events = PostgresEventRepository(sm)
    media = PostgresMediaRepository(sm)
    corr = PostgresMatchCorrectionRepository(sm)
    reads = PostgresNotificationReadRepository(sm)
    audit = PostgresDownloadAuditRepository(sm)

    a = await schools.create(name="A", max_teachers=5)
    login = await users.create(
        school_id=a.id, email="s@x.io", password_hash="h", role=Role.STUDENT
    )
    student = await students.create(
        school_id=a.id, user_id=login.id, name="N", reference_photo_path="p"
    )
    login2 = await users.create(
        school_id=a.id, email="s2@x.io", password_hash="h", role=Role.STUDENT
    )
    student2 = await students.create(
        school_id=a.id, user_id=login2.id, name="N2", reference_photo_path="p2"
    )
    ev = await events.create(
        school_id=a.id, name="E", description=None, event_date=None, created_by=None
    )
    m = await media.create(
        school_id=a.id, event_id=ev.id, storage_path="p1.jpg", media_type=MediaType.IMAGE
    )
    # The erased student's correction + notification-read + a self-download audit row,
    # plus the OTHER student's correction (must survive).
    await corr.upsert(
        school_id=a.id, media_id=m.id, student_id=student.id, event_id=ev.id,
        verdict=MatchVerdict.REJECTED, corrected_by=login.id, reason=None,
        resolves_review=False,
    )
    await corr.upsert(
        school_id=a.id, media_id=m.id, student_id=student2.id, event_id=ev.id,
        verdict=MatchVerdict.CONFIRMED, corrected_by=None, reason=None,
        resolves_review=False,
    )
    await reads.mark_seen(school_id=a.id, student_id=student.id, event_id=ev.id)
    await audit.record(
        school_id=a.id, media_id=m.id, event_id=ev.id, actor_user_id=login.id,
        actor_role="student", subject_student_id=student.id,
    )
    assert {c.student_id for c in await corr.list_for_media(a.id, m.id)} == {
        student.id, student2.id,
    }

    # Erase the student = delete the login (the cascade does the rest).
    await users.delete(login.id)

    assert await students.get(a.id, student.id) is None  # profile cascaded
    assert await students.get(a.id, student2.id) is not None  # the other survives
    # the student's correction cascaded away; the other student's remains
    assert {c.student_id for c in await corr.list_for_media(a.id, m.id)} == {student2.id}
    assert await reads.list_for_student(a.id, student.id) == {}  # notification-reads gone
    # the download-audit row survives, anonymized (subject + actor NULLed)
    entries = await audit.list_for_media(a.id, m.id, limit=10)
    assert len(entries) == 1
    assert entries[0].subject_student_id is None
    assert entries[0].actor_user_id is None


async def test_download_audit_record_list_and_scope(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    students = PostgresStudentRepository(sm)
    events = PostgresEventRepository(sm)
    media = PostgresMediaRepository(sm)
    audit = PostgresDownloadAuditRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    login = await users.create(
        school_id=a.id, email="s@x.io", password_hash="h", role=Role.STUDENT
    )
    student = await students.create(
        school_id=a.id, user_id=login.id, name="N", reference_photo_path="p"
    )
    staff = await users.create(
        school_id=a.id, email="t@x.io", password_hash="h", role=Role.SCHOOL_ADMIN
    )
    ev = await events.create(
        school_id=a.id, name="E", description=None, event_date=None, created_by=None
    )
    m = await media.create(
        school_id=a.id, event_id=ev.id, storage_path="p1.jpg", media_type=MediaType.IMAGE
    )

    assert await audit.count_for_media(a.id, m.id) == 0
    # A staff download (no subject) + a student self-download (subject = the student). Bracket
    # each with a wall-clock read so BP28a's date-range window can assert against the real
    # server-side created_at (which the test can't set directly).
    before = datetime.now(UTC) - timedelta(seconds=1)
    await audit.record(
        school_id=a.id, media_id=m.id, event_id=ev.id, actor_user_id=staff.id,
        actor_role="school_admin", subject_student_id=None,
    )
    await audit.record(
        school_id=a.id, media_id=m.id, event_id=ev.id, actor_user_id=login.id,
        actor_role="student", subject_student_id=student.id,
    )
    after = datetime.now(UTC) + timedelta(seconds=1)

    assert await audit.count_for_media(a.id, m.id) == 2
    entries = await audit.list_for_media(a.id, m.id, limit=10)
    assert len(entries) == 2
    assert {e.actor_role for e in entries} == {"school_admin", "student"}
    assert {e.subject_student_id for e in entries} == {None, student.id}
    # Newest-first: the student self-download (recorded second) leads. Verifies the real
    # SQL ORDER BY created_at DESC, not just the in-memory fake's sort.
    assert entries[0].actor_role == "student"
    assert entries[0].created_at >= entries[1].created_at

    # School-wide log + filters.
    assert await audit.count_recent(a.id) == 2
    by_student = await audit.list_recent(a.id, limit=10, offset=0, student_id=student.id)
    assert [e.actor_role for e in by_student] == ["student"]
    assert await audit.count_recent(a.id, event_id=ev.id) == 2
    assert await audit.count_recent(a.id, student_id=student.id) == 1

    # BP28a: date-range window on the REAL SQL (>= / <=). A window spanning both records
    # includes them; one entirely before the first excludes them.
    assert await audit.count_recent(a.id, created_from=before, created_to=after) == 2
    in_window = await audit.list_recent(
        a.id, limit=10, offset=0, created_from=before, created_to=after
    )
    assert len(in_window) == 2
    assert await audit.count_recent(a.id, created_to=before) == 0
    assert await audit.count_recent(a.id, created_from=after) == 0

    # BP28a: actor_role filter on the DENORMALIZED column. The student row's actor account is
    # then deleted (its actor_user_id FK SET NULL); the role stays, so the filter still matches.
    assert await audit.count_recent(a.id, actor_role="school_admin") == 1
    assert await audit.count_recent(a.id, actor_role="student") == 1
    await users.delete(login.id)  # remove the student's login account
    student_rows = await audit.list_recent(a.id, limit=10, offset=0, actor_role="student")
    assert len(student_rows) == 1
    assert student_rows[0].actor_role == "student"  # denormalized role survives
    assert student_rows[0].actor_user_id is None  # actor FK SET NULL after the delete
    assert await audit.count_recent(a.id, actor_role="student") == 1

    # Pagination.
    page1 = await audit.list_recent(a.id, limit=1, offset=0)
    page2 = await audit.list_recent(a.id, limit=1, offset=1)
    assert len(page1) == 1 and len(page2) == 1
    assert page1[0].id != page2[0].id
    # Newest-first across pages: page 1's row is at least as recent as page 2's.
    assert page1[0].created_at >= page2[0].created_at

    # Tenant-safe: a malformed/foreign school never leaks rows.
    assert await audit.list_for_media("not-a-uuid", m.id, limit=10) == []
    assert await audit.list_recent(_MISSING_UUID, limit=10, offset=0) == []
    assert await audit.count_for_media(_MISSING_UUID, m.id) == 0


async def test_student_get_by_user_id_is_tenant_scoped(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    students = PostgresStudentRepository(sm)
    school = await schools.create(name="A", max_teachers=5)
    login = await users.create(
        school_id=school.id, email="s@x.io", password_hash="h", role=Role.STUDENT
    )
    created = await students.create(
        school_id=school.id, user_id=login.id, name="Bart",
        reference_photo_path="reference-photos/a/p.jpg",
    )

    found = await students.get_by_user_id(school.id, login.id)
    assert found is not None and found.id == created.id
    # A foreign school never resolves the profile; a garbage id is None (not an error).
    assert await students.get_by_user_id("other-not-uuid", login.id) is None
    assert await students.get_by_user_id(school.id, str(_MISSING_UUID)) is None


async def test_student_read_model_reflects_login_status(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    # BP18d: the student read model carries the linked login's status off the users JOIN —
    # so disabling the login surfaces on the student's own reads (get/get_by_user_id/list),
    # which is what the FE shows + toggles. Written to the USER row; read on the student JOIN.
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    students = PostgresStudentRepository(sm)
    school = await schools.create(name="A", max_teachers=5)
    login = await users.create(
        school_id=school.id, email="s@x.io", password_hash="h", role=Role.STUDENT
    )
    created = await students.create(
        school_id=school.id, user_id=login.id, name="Bart",
        reference_photo_path="reference-photos/a/p.jpg",
    )
    assert created.status is UserStatus.ACTIVE  # fresh login is active

    await users.set_status(login.id, status=UserStatus.DISABLED)
    # Every read path reflects the disable (get / get_by_user_id / list_page).
    got = await students.get(school.id, created.id)
    assert got is not None and got.status is UserStatus.DISABLED
    by_user = await students.get_by_user_id(school.id, login.id)
    assert by_user is not None and by_user.status is UserStatus.DISABLED
    page = await students.list_page(school.id, limit=10, offset=0)
    assert [s.status for s in page if s.id == created.id] == [UserStatus.DISABLED]

    await users.set_status(login.id, status=UserStatus.ACTIVE)
    reenabled = await students.get(school.id, created.id)
    assert reenabled is not None and reenabled.status is UserStatus.ACTIVE


# ---- BP9: paginated list SQL (decisions/0055) -----------------------------


async def test_student_list_page_search_sort_filter_pagination(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    students = PostgresStudentRepository(sm)
    a = await schools.create(name="A", max_teachers=50)
    b = await schools.create(name="B", max_teachers=50)

    async def add(
        school_id: str, *, email: str, name: str,
        status: EnrollmentStatus = EnrollmentStatus.PENDING,
    ) -> None:
        login = await users.create(
            school_id=school_id, email=email, password_hash="h", role=Role.STUDENT
        )
        s = await students.create(
            school_id=school_id, user_id=login.id, name=name, reference_photo_path="p"
        )
        if status is not EnrollmentStatus.PENDING:
            await students.set_enrollment(s.id, status=status)

    await add(a.id, email="anna@a.io", name="Anna", status=EnrollmentStatus.ENROLLED)
    await add(a.id, email="bob@a.io", name="Bob")
    await add(a.id, email="cara@a.io", name="Cara", status=EnrollmentStatus.ENROLLED)
    await add(a.id, email="dan@a.io", name="Dan", status=EnrollmentStatus.FAILED)
    await add(a.id, email="eve@a.io", name="Eve", status=EnrollmentStatus.ENROLLED)
    # Literal-% names to prove the ILIKE metacharacters are escaped in search.
    await add(a.id, email="pct@a.io", name="50%OFF")
    await add(a.id, email="club@a.io", name="500 club")
    await add(b.id, email="x@b.io", name="Alien")  # other school — never appears

    # Tenant-scoped total (7 in A, not B's student).
    assert await students.count_page(a.id) == 7

    # Default page (name asc): the letter names come out A..E (collation-robust).
    page = await students.list_page(a.id, limit=50, offset=0)
    letters = [s.name for s in page if len(s.name) <= 4]
    assert letters == ["Anna", "Bob", "Cara", "Dan", "Eve"]

    # Search escapes % -> "50%" matches only the literal "50%OFF", not "500 club".
    pct = await students.list_page(a.id, limit=50, offset=0, q="50%")
    assert [s.name for s in pct] == ["50%OFF"]
    assert await students.count_page(a.id, q="50%") == 1
    assert await students.count_page(a.id, q="500") == 1  # "500 club" only

    # Search hits the joined login email too.
    by_email = await students.list_page(a.id, limit=50, offset=0, q="bob@")
    assert [s.name for s in by_email] == ["Bob"]

    # Status filter + its count.
    enrolled = await students.list_page(
        a.id, limit=50, offset=0, status=EnrollmentStatus.ENROLLED
    )
    assert {s.name for s in enrolled} == {"Anna", "Cara", "Eve"}
    assert await students.count_page(a.id, status=EnrollmentStatus.ENROLLED) == 3

    # Sort desc + pagination slices the enrolled subset without overlap.
    p1 = await students.list_page(
        a.id, limit=2, offset=0, sort=StudentSort.NAME, descending=True,
        status=EnrollmentStatus.ENROLLED,
    )
    p2 = await students.list_page(
        a.id, limit=2, offset=2, sort=StudentSort.NAME, descending=True,
        status=EnrollmentStatus.ENROLLED,
    )
    assert [s.name for s in p1] == ["Eve", "Cara"]
    assert [s.name for s in p2] == ["Anna"]

    # list_ids returns exactly the filtered ids (the count-sort path consumes these).
    ids = await students.list_ids(a.id, status=EnrollmentStatus.ENROLLED)
    assert len(ids) == 3

    # Malformed tenant id -> empty/zero, never an error.
    assert await students.list_page("not-a-uuid", limit=10, offset=0) == []
    assert await students.count_page("not-a-uuid") == 0
    assert await students.list_ids("not-a-uuid") == []


async def test_list_by_ids_is_tenant_scoped(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    students = PostgresStudentRepository(sm)
    events = PostgresEventRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    b = await schools.create(name="B", max_teachers=5)

    login_a = await users.create(
        school_id=a.id, email="sa@a.io", password_hash="h", role=Role.STUDENT
    )
    login_b = await users.create(
        school_id=b.id, email="sb@b.io", password_hash="h", role=Role.STUDENT
    )
    sa = await students.create(
        school_id=a.id, user_id=login_a.id, name="A", reference_photo_path="p"
    )
    sb = await students.create(
        school_id=b.id, user_id=login_b.id, name="B", reference_photo_path="p"
    )

    # A foreign id + a malformed id are dropped; only the in-tenant row comes back.
    got = await students.list_by_ids(a.id, [sa.id, sb.id, "not-a-uuid", _MISSING_UUID])
    assert [s.id for s in got] == [sa.id]
    assert await students.list_by_ids(a.id, []) == []

    ea = await events.create(
        school_id=a.id, name="EA", description=None, event_date=None, created_by=None
    )
    eb = await events.create(
        school_id=b.id, name="EB", description=None, event_date=None, created_by=None
    )
    egot = await events.list_by_ids(a.id, [ea.id, eb.id])
    assert [e.id for e in egot] == [ea.id]


async def test_resolve_by_emails_is_case_insensitive_and_tenant_scoped(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    # BP10 filename → student: match the login email (case-insensitive), never cross-tenant.
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    students = PostgresStudentRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    b = await schools.create(name="B", max_teachers=5)

    login_a = await users.create(
        school_id=a.id, email="alice@a.io", password_hash="h", role=Role.STUDENT
    )
    login_b = await users.create(
        school_id=b.id, email="bob@b.io", password_hash="h", role=Role.STUDENT
    )
    sa = await students.create(
        school_id=a.id, user_id=login_a.id, name="Alice", reference_photo_path="p"
    )
    await students.create(
        school_id=b.id, user_id=login_b.id, name="Bob", reference_photo_path="p"
    )

    # Case-insensitive match; an unknown email is simply absent from the result.
    got = await students.resolve_by_emails(a.id, ["ALICE@A.io", "nobody@a.io"])
    assert [s.id for s in got] == [sa.id]

    # Tenant-scoped: school B's email never resolves for school A (no cross-tenant leak).
    assert await students.resolve_by_emails(a.id, ["bob@b.io"]) == []
    # Empty input + a malformed school id both return nothing (defensive, like the other reads).
    assert await students.resolve_by_emails(a.id, []) == []
    assert await students.resolve_by_emails("not-a-uuid", ["alice@a.io"]) == []


async def test_student_group_crud_counts_join_filter_and_cascade(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    # BP11a: the class CRUD + counts, the students LEFT JOIN carrying the class name, the
    # class filter on the paginated reads, and the ON DELETE SET NULL cascade — end to end.
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    students = PostgresStudentRepository(sm)
    groups = PostgresStudentGroupRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    b = await schools.create(name="B", max_teachers=5)

    # create + get + list, tenant-scoped
    c = await groups.create(school_id=a.id, name="Grade 3B", grade="3", section="B")
    assert c.id and (c.name, c.grade, c.section) == ("Grade 3B", "3", "B")
    assert await groups.get(a.id, c.id) is not None
    assert await groups.get(b.id, c.id) is None  # foreign school can't see it
    assert await groups.get(a.id, "not-a-uuid") is None
    assert [g.id for g in await groups.list_by_school(a.id)] == [c.id]
    assert await groups.list_by_school(b.id) == []

    # update replaces fields; a foreign school can't
    updated = await groups.update(a.id, c.id, name="Grade 4A", grade="4", section="A")
    assert updated is not None and updated.name == "Grade 4A"
    assert await groups.update(b.id, c.id, name="x", grade=None, section=None) is None

    # assign two students (one left un-classed) and count
    logins = [
        await users.create(
            school_id=a.id, email=f"s{i}@a.io", password_hash="h", role=Role.STUDENT
        )
        for i in range(3)
    ]
    p1 = await students.create(school_id=a.id, user_id=logins[0].id, name="P1")
    p2 = await students.create(school_id=a.id, user_id=logins[1].id, name="P2")
    await students.create(school_id=a.id, user_id=logins[2].id, name="P3")  # un-classed
    assert (
        await students.set_group_bulk(
            a.id, student_group_id=c.id, student_ids=[p1.id, p2.id]
        )
        == 2
    )
    assert await groups.student_counts(a.id) == {c.id: 2}

    # the student read carries the class name (LEFT JOIN) + the list filters by class
    got = await students.get(a.id, p1.id)
    assert got is not None and got.student_group_id == c.id
    assert got.student_group_name == "Grade 4A"
    in_class = await students.list_page(a.id, limit=50, offset=0, student_group_id=c.id)
    assert {s.id for s in in_class} == {p1.id, p2.id}
    assert await students.count_page(a.id, student_group_id=c.id) == 2
    assert set(await students.list_ids(a.id, student_group_id=c.id)) == {p1.id, p2.id}

    # single set_group can clear
    await students.set_group(p1.id, student_group_id=None)
    cleared = await students.get(a.id, p1.id)
    assert cleared is not None and cleared.student_group_id is None
    assert cleared.student_group_name is None

    # delete the class → the remaining member (p2) is SET NULL, and the class is gone
    assert await groups.delete(a.id, c.id) is True
    left = await students.get(a.id, p2.id)
    assert left is not None and left.student_group_id is None
    assert await groups.get(a.id, c.id) is None
    assert await groups.delete(a.id, c.id) is False  # already gone


async def test_set_group_bulk_never_moves_a_foreign_student(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    # A class of school A can never pull in a student of school B (tenant-scoped UPDATE).
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    students = PostgresStudentRepository(sm)
    groups = PostgresStudentGroupRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    b = await schools.create(name="B", max_teachers=5)
    c = await groups.create(school_id=a.id, name="A-class", grade=None, section=None)
    login = await users.create(
        school_id=b.id, email="foreign@b.io", password_hash="h", role=Role.STUDENT
    )
    foreign = await students.create(school_id=b.id, user_id=login.id, name="Foreign")

    assert (
        await students.set_group_bulk(
            a.id, student_group_id=c.id, student_ids=[foreign.id]
        )
        == 0
    )
    still = await students.get(b.id, foreign.id)
    assert still is not None and still.student_group_id is None


async def test_event_category_crud_seed_join_filters_and_cascade(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    # BP11b: category CRUD + seed + the events LEFT JOIN carrying the name + the
    # category/term/date-range filters + the SET NULL cascade — end to end on real SQL.
    schools = PostgresSchoolRepository(sm)
    events = PostgresEventRepository(sm)
    cats = PostgresEventCategoryRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    b = await schools.create(name="B", max_teachers=5)

    # seed (idempotent) + list + tenant scope + case-insensitive name lookup
    await cats.seed_defaults(a.id, ("Sports", "Academic", "Other"))
    await cats.seed_defaults(a.id, ("Sports", "Trip"))  # skips the existing Sports
    listed = await cats.list_by_school(a.id)
    assert sorted(c.name for c in listed) == ["Academic", "Other", "Sports", "Trip"]
    assert await cats.list_by_school(b.id) == []
    sports = await cats.get_by_name(a.id, "SPORTS")
    assert sports is not None and sports.name == "Sports"
    assert await cats.get(b.id, sports.id) is None  # foreign school can't see it

    # the (school_id, name) UNIQUE is enforced at the DB
    with pytest.raises(IntegrityError):
        await cats.create(school_id=a.id, name="Sports")

    # create events with a category + term; the LEFT JOIN carries the category name
    e1 = await events.create(
        school_id=a.id,
        name="Sports Day",
        description=None,
        event_date=date(2026, 7, 4),
        created_by=None,
        category_id=sports.id,
        term="Fall 2026",
    )
    assert e1.category_id == sports.id and e1.category_name == "Sports"
    await events.create(
        school_id=a.id,
        name="Undated",
        description=None,
        event_date=None,
        created_by=None,
        category_id=sports.id,
        term="Fall 2026",
    )
    got = await events.get(a.id, e1.id)
    assert got is not None and got.category_name == "Sports"

    # filters: category / term / date-range (a null date is excluded)
    by_cat = await events.list_page(a.id, limit=50, offset=0, category_id=sports.id)
    assert {e.name for e in by_cat} == {"Sports Day", "Undated"}
    assert await events.count_page(a.id, category_id=sports.id) == 2
    assert len(await events.list_page(a.id, limit=50, offset=0, term="Fall 2026")) == 2
    in_range = await events.list_page(
        a.id, limit=50, offset=0, date_from=date(2026, 7, 1), date_to=date(2026, 7, 31)
    )
    assert {e.name for e in in_range} == {"Sports Day"}  # the undated one is excluded
    assert await events.list_terms(a.id) == ["Fall 2026"]

    # delete the category → its events are un-tagged (SET NULL), not deleted
    assert await cats.delete(a.id, sports.id) is True
    after = await events.get(a.id, e1.id)
    assert after is not None and after.category_id is None and after.category_name is None
    assert await cats.get(a.id, sports.id) is None
    assert await cats.delete(a.id, sports.id) is False  # already gone


async def test_teacher_class_links_and_event_group_scope_and_cascade(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    # BP11c: the teacher↔class link (add idempotent / both directions / remove / replace /
    # tenant scope), the events LEFT JOIN carrying the class name + the class filter + the
    # focus scope (class events OR untagged), and the two SET-NULL/CASCADE deletes — end to
    # end on real SQL.
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    events = PostgresEventRepository(sm)
    groups = PostgresStudentGroupRepository(sm)
    links = PostgresTeacherClassRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    b = await schools.create(name="B", max_teachers=5)
    c1 = await groups.create(school_id=a.id, name="3A", grade="3", section="A")
    c2 = await groups.create(school_id=a.id, name="3B", grade="3", section="B")
    t1 = await users.create(
        school_id=a.id, email="t1@a.io", password_hash="h", role=Role.TEACHER
    )
    t2 = await users.create(
        school_id=a.id, email="t2@a.io", password_hash="h", role=Role.TEACHER
    )

    # add is idempotent; links resolve both directions; tenant-scoped
    await links.add(school_id=a.id, teacher_user_id=t1.id, student_group_id=c1.id)
    await links.add(school_id=a.id, teacher_user_id=t1.id, student_group_id=c1.id)  # no-op
    await links.add(school_id=a.id, teacher_user_id=t2.id, student_group_id=c1.id)
    assert await links.list_group_ids_for_teacher(a.id, t1.id) == [c1.id]
    assert set(await links.list_teacher_ids_for_group(a.id, c1.id)) == {t1.id, t2.id}
    assert await links.list_group_ids_for_teacher(b.id, t1.id) == []  # foreign school

    # remove returns whether a row went; a second remove is False
    assert await links.remove(
        school_id=a.id, teacher_user_id=t2.id, student_group_id=c1.id
    ) is True
    assert await links.remove(
        school_id=a.id, teacher_user_id=t2.id, student_group_id=c1.id
    ) is False

    # replace_for_teacher sets the whole set atomically (dedupes a repeated id)
    await links.replace_for_teacher(
        school_id=a.id, teacher_user_id=t1.id, student_group_ids=[c1.id, c2.id, c2.id]
    )
    assert set(await links.list_group_ids_for_teacher(a.id, t1.id)) == {c1.id, c2.id}

    # events carry the class name (LEFT JOIN); the class filter + the focus scope work
    e1 = await events.create(
        school_id=a.id, name="Cls", description=None, event_date=None,
        created_by=None, student_group_id=c1.id,
    )
    await events.create(
        school_id=a.id, name="Other", description=None, event_date=None,
        created_by=None, student_group_id=c2.id,
    )
    await events.create(
        school_id=a.id, name="Assembly", description=None, event_date=None,
        created_by=None,  # untagged / school-wide
    )
    got = await events.get(a.id, e1.id)
    assert got is not None and got.student_group_id == c1.id
    assert got.student_group_name == "3A"
    by_class = await events.list_page(a.id, limit=50, offset=0, student_group_id=c1.id)
    assert {e.name for e in by_class} == {"Cls"}
    # focus scope: the teacher's classes' events PLUS the untagged school-wide event
    focused = await events.list_page(
        a.id, limit=50, offset=0, scope_group_ids=[c1.id]
    )
    assert {e.name for e in focused} == {"Cls", "Assembly"}
    # an empty focus scope leaves only the untagged events
    only_untagged = await events.list_page(
        a.id, limit=50, offset=0, scope_group_ids=[]
    )
    assert {e.name for e in only_untagged} == {"Assembly"}

    # delete the class → its events SET NULL and its teacher links CASCADE away
    assert await groups.delete(a.id, c1.id) is True
    after = await events.get(a.id, e1.id)
    assert after is not None and after.student_group_id is None
    assert after.student_group_name is None
    assert await links.list_teacher_ids_for_group(a.id, c1.id) == []  # links cascaded

    # deleting the teacher (a users row) cascades its remaining links away too
    remaining = await links.list_group_ids_for_teacher(a.id, t1.id)
    assert remaining == [c2.id]
    await users.delete(t1.id)
    assert await links.list_group_ids_for_teacher(a.id, t1.id) == []


async def test_event_set_status_bulk_is_tenant_scoped(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    # BP13: bulk archive/restore sets the status on many of one school's events in one UPDATE,
    # and never touches another school's event.
    schools = PostgresSchoolRepository(sm)
    events = PostgresEventRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    b = await schools.create(name="B", max_teachers=5)
    e1 = await events.create(
        school_id=a.id, name="E1", description=None, event_date=None, created_by=None
    )
    e2 = await events.create(
        school_id=a.id, name="E2", description=None, event_date=None, created_by=None
    )
    ef = await events.create(
        school_id=b.id, name="Foreign", description=None, event_date=None, created_by=None
    )

    # Archive e1 + e2 (a's) and try to sneak in ef (b's) — ef is silently skipped.
    updated = await events.set_status_bulk(
        a.id, [e1.id, e2.id, ef.id, _MISSING_UUID, "not-a-uuid"], status=EventStatus.ARCHIVED
    )
    assert updated == 2
    assert (await events.get(a.id, e1.id)).status is EventStatus.ARCHIVED  # type: ignore[union-attr]
    assert (await events.get(a.id, e2.id)).status is EventStatus.ARCHIVED  # type: ignore[union-attr]
    # b's event was never touched (still active).
    assert (await events.get(b.id, ef.id)).status is EventStatus.ACTIVE  # type: ignore[union-attr]

    # Restore e1.
    assert await events.set_status_bulk(a.id, [e1.id], status=EventStatus.ACTIVE) == 1
    assert (await events.get(a.id, e1.id)).status is EventStatus.ACTIVE  # type: ignore[union-attr]


# ---- BP14 analytics aggregates (decisions/0062) -------------------------


async def test_bp14_user_signin_aggregates(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    # touch_last_login sets the signal; the count aggregates are role- and tenant-scoped.
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    b = await schools.create(name="B", max_teachers=5)
    s1 = await users.create(school_id=a.id, email="s1@a.io", password_hash="h", role=Role.STUDENT)
    s2 = await users.create(school_id=a.id, email="s2@a.io", password_hash="h", role=Role.STUDENT)
    await users.create(school_id=a.id, email="s3@a.io", password_hash="h", role=Role.STUDENT)
    t1 = await users.create(school_id=a.id, email="t1@a.io", password_hash="h", role=Role.TEACHER)
    bs = await users.create(school_id=b.id, email="s@b.io", password_hash="h", role=Role.STUDENT)

    # No one has signed in yet.
    assert await users.count_signed_in_by_school_and_role(a.id, Role.STUDENT) == 0
    assert await users.signed_in_role_counts_by_school() == {}

    await users.touch_last_login(s1.id)
    await users.touch_last_login(s2.id)
    await users.touch_last_login(t1.id)
    await users.touch_last_login(bs.id)  # the OTHER school
    await users.touch_last_login("not-a-uuid")  # no-op, no raise

    # 2 of 3 A-students signed in; the teacher and B's student never bleed in.
    assert await users.count_signed_in_by_school_and_role(a.id, Role.STUDENT) == 2
    assert await users.count_signed_in_by_school_and_role(a.id, Role.TEACHER) == 1
    counts = await users.signed_in_role_counts_by_school()
    assert counts[a.id] == {Role.STUDENT: 2, Role.TEACHER: 1}
    assert counts[b.id] == {Role.STUDENT: 1}


async def test_bp14_analytics_grouped_aggregates(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    students = PostgresStudentRepository(sm)
    events = PostgresEventRepository(sm)
    media = PostgresMediaRepository(sm)
    reads = PostgresNotificationReadRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    b = await schools.create(name="B", max_teachers=5)

    # A: 2 enrolled + 1 pending student; B: 1 enrolled.
    async def _student(school_id: str, tag: str, status: EnrollmentStatus) -> str:
        login = await users.create(
            school_id=school_id, email=f"{tag}@x.io", password_hash="h", role=Role.STUDENT
        )
        s = await students.create(
            school_id=school_id, user_id=login.id, name=tag,
            reference_photo_path=f"reference-photos/{tag}.jpg",
        )
        await students.set_enrollment(s.id, status=status)
        return s.id

    sa1 = await _student(a.id, "a1", EnrollmentStatus.ENROLLED)
    await _student(a.id, "a2", EnrollmentStatus.ENROLLED)
    await _student(a.id, "a3", EnrollmentStatus.PENDING)
    await _student(b.id, "b1", EnrollmentStatus.ENROLLED)

    assert await students.enrolled_counts_by_school() == {a.id: 2, b.id: 1}

    # A: 2 events (both dated in the same month), one announced; B: 1 event, not announced.
    async def _event(school_id: str, name: str, event_date: date | None) -> str:
        ev = await events.create(
            school_id=school_id, name=name, description=None,
            event_date=event_date, created_by=None,
        )
        return ev.id

    ea1 = await _event(a.id, "A1", date(2026, 3, 4))
    ea2 = await _event(a.id, "A2", date(2026, 3, 20))
    eb1 = await _event(b.id, "B1", date(2026, 4, 1))
    await _event(a.id, "A3", None)  # undated — excluded from the by-date trend
    await events.mark_notified(ea1)

    assert await events.distributed_counts_by_school() == {a.id: 1}  # only ea1

    # recent_event_counts: created_at is server-now, so a far-past cutoff sees all, a
    # far-future cutoff sees none (A has 3 events, B has 1).
    all_recent = await events.recent_event_counts_by_school(datetime(2000, 1, 1, tzinfo=UTC))
    assert all_recent == {a.id: 3, b.id: 1}
    none_recent = await events.recent_event_counts_by_school(
        datetime.now(UTC) + timedelta(days=1)
    )
    assert none_recent == {}

    # monthly_event_date_counts (tenant-scoped): A's 2 dated events land in 2026-03; the
    # undated one is excluded, and B's event never leaks.
    a_months = await events.monthly_event_date_counts(a.id)
    assert a_months == {"2026-03": 2}

    # media: 2 photos in A's ea1, 1 in B's eb1.
    async def _photo(school_id: str, event_id: str, path: str) -> None:
        await media.create(
            school_id=school_id, event_id=event_id, storage_path=path,
            media_type=MediaType.IMAGE,
        )

    await _photo(a.id, ea1, "p1.jpg")
    await _photo(a.id, ea1, "p2.jpg")
    await _photo(b.id, eb1, "p3.jpg")
    a_upload_months = await media.monthly_upload_counts(a.id)
    assert sum(a_upload_months.values()) == 2 and len(a_upload_months) == 1

    # count_distinct_seen_students: a1 opens two events (counts once), a2 opens one.
    await reads.mark_seen(school_id=a.id, student_id=sa1, event_id=ea1)
    await reads.mark_seen(school_id=a.id, student_id=sa1, event_id=ea2)
    a2_id = next(s.id for s in await students.list_by_school(a.id) if s.name == "a2")
    await reads.mark_seen(school_id=a.id, student_id=a2_id, event_id=ea1)
    assert await reads.count_distinct_seen_students(a.id) == 2
    assert await reads.count_distinct_seen_students(b.id) == 0


# ---- BP23 instrumentation aggregates (decisions/0078) -------------------


async def test_bp23_media_uploaded_by_round_trip_and_set_null(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    # media.uploaded_by (migration 0019) persists + defaults None, and its FK is SET NULL —
    # deleting the uploader's account leaves the row with a null uploader (never orphaned).
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    events = PostgresEventRepository(sm)
    media = PostgresMediaRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    uploader = await users.create(
        school_id=a.id, email="t@a.io", password_hash="h", role=Role.TEACHER
    )
    ev = await events.create(
        school_id=a.id, name="E", description=None, event_date=None, created_by=None
    )
    attributed = await media.create(
        school_id=a.id, event_id=ev.id, storage_path="events/a/e/p.jpg",
        media_type=MediaType.IMAGE, uploaded_by=uploader.id,
    )
    assert attributed.uploaded_by == uploader.id
    anon = await media.create(
        school_id=a.id, event_id=ev.id, storage_path="events/a/e/q.jpg",
        media_type=MediaType.IMAGE,  # no uploader -> None
    )
    assert anon.uploaded_by is None

    # SET NULL on uploader delete (the row outlives the account).
    await users.delete(uploader.id)
    reread = await media.get(a.id, attributed.id)
    assert reread is not None and reread.uploaded_by is None


async def test_bp23_last_login_at_exposed_and_sortable(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    # last_login_at is mapped onto the read model + is a row-native sort (nulls last on ASC).
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    t1 = await users.create(
        school_id=a.id, email="t1@a.io", password_hash="h", role=Role.TEACHER
    )
    await users.create(
        school_id=a.id, email="t2@a.io", password_hash="h", role=Role.TEACHER
    )
    # Fresh accounts have a null last_login_at.
    assert (await users.get(t1.id)).last_login_at is None  # type: ignore[union-attr]
    await users.touch_last_login(t1.id)
    assert (await users.get(t1.id)).last_login_at is not None  # type: ignore[union-attr]

    # Sorting by last_login_at ASC puts the never-signed-in account last (NULLS LAST).
    page = await users.list_page_by_role(
        a.id, Role.TEACHER, limit=10, offset=0, sort=UserSort.LAST_LOGIN_AT,
        descending=False,
    )
    assert [u.email for u in page] == ["t1@a.io", "t2@a.io"]


async def test_bp23_notification_read_reach_and_first_open_aggregates(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    students = PostgresStudentRepository(sm)
    events = PostgresEventRepository(sm)
    reads = PostgresNotificationReadRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    b = await schools.create(name="B", max_teachers=5)

    async def _student(school_id: str, email: str) -> str:
        login = await users.create(
            school_id=school_id, email=email, password_hash="h", role=Role.STUDENT
        )
        s = await students.create(
            school_id=school_id, user_id=login.id, name=email, reference_photo_path="p"
        )
        return s.id

    sa1 = await _student(a.id, "a1@a.io")
    sa2 = await _student(a.id, "a2@a.io")
    sb1 = await _student(b.id, "b1@b.io")
    ea1 = (await events.create(school_id=a.id, name="E1", description=None,
                               event_date=None, created_by=None)).id
    ea2 = (await events.create(school_id=a.id, name="E2", description=None,
                               event_date=None, created_by=None)).id
    eb1 = (await events.create(school_id=b.id, name="EB", description=None,
                               event_date=None, created_by=None)).id

    await reads.mark_seen(school_id=a.id, student_id=sa1, event_id=ea1)
    await reads.mark_seen(school_id=a.id, student_id=sa2, event_id=ea1)
    await reads.mark_seen(school_id=a.id, student_id=sa1, event_id=ea2)
    await reads.mark_seen(school_id=b.id, student_id=sb1, event_id=eb1)

    # reach: A has 2 distinct opened events (ea1, ea2); B has 1; tenant-scoped.
    assert set(await reads.distinct_opened_event_ids(a.id)) == {ea1, ea2}
    assert set(await reads.distinct_opened_event_ids(b.id)) == {eb1}
    assert await reads.distinct_opened_event_ids("not-a-uuid") == []

    # first-open trend: 3 first-opens for A, all in the current month (created_at now()).
    a_trend = await reads.monthly_first_open_counts(a.id)
    assert sum(a_trend.values()) == 3 and len(a_trend) == 1

    # first_seen_for_event: ea1 has sa1 + sa2 (their immutable created_at), keyed by student.
    ea1_first = await reads.first_seen_for_event(a.id, ea1)
    assert set(ea1_first) == {sa1, sa2}
    assert await reads.first_seen_for_event("not-a-uuid", ea1) == {}


async def test_bp23_download_audit_saver_aggregates(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    students = PostgresStudentRepository(sm)
    events = PostgresEventRepository(sm)
    media = PostgresMediaRepository(sm)
    audit = PostgresDownloadAuditRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    b = await schools.create(name="B", max_teachers=5)

    async def _student(school_id: str, email: str) -> tuple[str, str]:
        login = await users.create(
            school_id=school_id, email=email, password_hash="h", role=Role.STUDENT
        )
        s = await students.create(
            school_id=school_id, user_id=login.id, name=email, reference_photo_path="p"
        )
        return login.id, s.id

    staff = await users.create(
        school_id=a.id, email="staff@a.io", password_hash="h", role=Role.SCHOOL_ADMIN
    )
    a_login, a_student = await _student(a.id, "a1@a.io")
    b_login, b_student = await _student(b.id, "b1@b.io")
    ev = await events.create(school_id=a.id, name="E", description=None,
                             event_date=None, created_by=None)
    m = await media.create(school_id=a.id, event_id=ev.id, storage_path="p.jpg",
                           media_type=MediaType.IMAGE)
    evb = await events.create(school_id=b.id, name="EB", description=None,
                              event_date=None, created_by=None)
    mb = await media.create(school_id=b.id, event_id=evb.id, storage_path="pb.jpg",
                            media_type=MediaType.IMAGE)

    # A student self-download (counts) + a staff download of the same media (must NOT count).
    await audit.record(school_id=a.id, media_id=m.id, event_id=ev.id,
                       actor_user_id=a_login, actor_role="student",
                       subject_student_id=a_student)
    await audit.record(school_id=a.id, media_id=m.id, event_id=ev.id,
                       actor_user_id=a_login, actor_role="student",
                       subject_student_id=a_student)  # a second self-save
    await audit.record(school_id=a.id, media_id=m.id, event_id=ev.id,
                       actor_user_id=staff.id, actor_role="school_admin",
                       subject_student_id=None)
    await audit.record(school_id=b.id, media_id=mb.id, event_id=evb.id,
                       actor_user_id=b_login, actor_role="student",
                       subject_student_id=b_student)

    # distinct savers: A = 1 (only a_student; staff excluded), B = 1; tenant-scoped.
    assert await audit.count_distinct_saver_students(a.id) == 1
    assert await audit.count_distinct_saver_students(b.id) == 1
    assert await audit.count_distinct_saver_students("not-a-uuid") == 0

    # per-event per-student download count: a_student has 2 saves in ev; B never leaks.
    counts = await audit.download_counts_by_student_for_event(a.id, ev.id)
    assert counts == {a_student: 2}
    assert await audit.download_counts_by_student_for_event(a.id, evb.id) == {}


async def test_bp23_match_correction_monthly_verdicts(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    students = PostgresStudentRepository(sm)
    events = PostgresEventRepository(sm)
    media = PostgresMediaRepository(sm)
    corr = PostgresMatchCorrectionRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    b = await schools.create(name="B", max_teachers=5)
    staff = await users.create(school_id=a.id, email="t@a.io", password_hash="h",
                               role=Role.TEACHER)
    ev = await events.create(school_id=a.id, name="E", description=None,
                             event_date=None, created_by=None)

    async def _student_media(email: str, path: str) -> tuple[str, str]:
        login = await users.create(school_id=a.id, email=email, password_hash="h",
                                   role=Role.STUDENT)
        s = await students.create(school_id=a.id, user_id=login.id, name=email,
                                  reference_photo_path="p")
        m = await media.create(school_id=a.id, event_id=ev.id, storage_path=path,
                               media_type=MediaType.IMAGE)
        return s.id, m.id

    s1, m1 = await _student_media("s1@a.io", "p1.jpg")
    s2, m2 = await _student_media("s2@a.io", "p2.jpg")
    s3, m3 = await _student_media("s3@a.io", "p3.jpg")
    for sid, mid, verdict in (
        (s1, m1, MatchVerdict.CONFIRMED),
        (s2, m2, MatchVerdict.REJECTED),
        (s3, m3, MatchVerdict.ADDED),
    ):
        await corr.upsert(school_id=a.id, media_id=mid, student_id=sid, event_id=ev.id,
                          verdict=verdict, corrected_by=staff.id, reason=None,
                          resolves_review=False)

    monthly = await corr.monthly_verdict_counts(a.id)
    # All in the current month (created_at now()); one bucket, one of each verdict.
    assert len(monthly) == 1
    per = next(iter(monthly.values()))
    assert per == {
        MatchVerdict.CONFIRMED: 1,
        MatchVerdict.REJECTED: 1,
        MatchVerdict.ADDED: 1,
    }
    # tenant-scoped: B has no corrections.
    assert await corr.monthly_verdict_counts(b.id) == {}


async def test_bp23_estate_age_aggregates(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    schools = PostgresSchoolRepository(sm)
    events = PostgresEventRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    b = await schools.create(name="B", max_teachers=5)

    # A: two announced events (mark_notified). B: one un-announced event (auto but not completed).
    ea1 = await events.create(school_id=a.id, name="E1", description=None,
                              event_date=None, created_by=None)
    ea2 = await events.create(school_id=a.id, name="E2", description=None,
                              event_date=None, created_by=None)
    await events.mark_notified(ea1.id)
    await events.mark_notified(ea2.id)
    eb1 = await events.create(school_id=b.id, name="EB", description=None,
                              event_date=None, created_by=None)  # not announced

    # first_distributed_at: A present = min(notified_at of ea1, ea2); B absent (un-announced).
    first_dist = await events.first_distributed_at_by_school()
    ea1n = await events.get(a.id, ea1.id)
    ea2n = await events.get(a.id, ea2.id)
    assert ea1n is not None and ea2n is not None
    assert ea1n.notified_at is not None and ea2n.notified_at is not None
    assert first_dist[a.id] == min(ea1n.notified_at, ea2n.notified_at)
    assert b.id not in first_dist

    # last_event_created_at: A = max(ea1, ea2 created_at); B = eb1 created_at (present).
    last_created = await events.last_event_created_at_by_school()
    assert last_created[a.id] == max(ea1.created_at, ea2.created_at)
    assert last_created[b.id] == eb1.created_at


async def test_bp23_student_activity_filters(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    # never_signed_in (users.last_login_at IS NULL) + never_opened (a same-schema NOT EXISTS
    # over notification_reads) — tenant-scoped, threaded through list_ids/count_page.
    schools = PostgresSchoolRepository(sm)
    users = PostgresUserRepository(sm)
    students = PostgresStudentRepository(sm)
    events = PostgresEventRepository(sm)
    reads = PostgresNotificationReadRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    b = await schools.create(name="B", max_teachers=5)

    async def _student(school_id: str, email: str) -> tuple[str, str]:
        login = await users.create(school_id=school_id, email=email, password_hash="h",
                                   role=Role.STUDENT)
        s = await students.create(school_id=school_id, user_id=login.id, name=email,
                                  reference_photo_path="p")
        return login.id, s.id

    u1, s1 = await _student(a.id, "s1@a.io")
    _u2, s2 = await _student(a.id, "s2@a.io")
    _u3, s3 = await _student(a.id, "s3@a.io")
    _ub, sb = await _student(b.id, "sb@b.io")  # other school — must never leak

    ev = await events.create(school_id=a.id, name="E", description=None,
                             event_date=None, created_by=None)
    await users.touch_last_login(u1)  # s1 signed in
    await reads.mark_seen(school_id=a.id, student_id=s2, event_id=ev.id)  # s2 opened

    # never signed in -> s2, s3 (u2, u3 never logged in); s1 excluded; B never leaks.
    never_signed = set(await students.list_ids(a.id, never_signed_in=True))
    assert never_signed == {s2, s3}
    assert await students.count_page(a.id, never_signed_in=True) == 2

    # never opened -> s1, s3 (s2 has a read); tenant-scoped.
    never_opened = set(await students.list_ids(a.id, never_opened=True))
    assert never_opened == {s1, s3}

    # combined -> s3 only (never signed in AND never opened).
    both = set(
        await students.list_ids(a.id, never_signed_in=True, never_opened=True)
    )
    assert both == {s3}

    # B's student is unaffected by A's filters and only shows in B's scope.
    assert sb not in never_signed and sb not in never_opened
    assert set(await students.list_ids(b.id, never_signed_in=True)) == {sb}


# ---- BP24 clearable event tags (decisions/0079) -------------------------


async def test_bp24_event_update_clears_and_leaves_tags(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    # The tri-state PATCH on the real repo: UNSET (omitted) leaves a tag unchanged; an explicit
    # None clears it to NULL; a value sets it — the 0027 revision, on Postgres.
    schools = PostgresSchoolRepository(sm)
    events = PostgresEventRepository(sm)
    categories = PostgresEventCategoryRepository(sm)
    groups = PostgresStudentGroupRepository(sm)
    a = await schools.create(name="A", max_teachers=5)
    cat = await categories.create(school_id=a.id, name="Sports")
    grp = await groups.create(school_id=a.id, name="3B", grade=None, section=None)
    ev = await events.create(
        school_id=a.id, name="E", description=None, event_date=None, created_by=None,
        category_id=cat.id, term="Fall", student_group_id=grp.id,
    )
    assert ev.category_id == cat.id and ev.term == "Fall" and ev.student_group_id == grp.id

    # UNSET (the three tag args omitted) leaves them unchanged; only name changes.
    u1 = await events.update(a.id, ev.id, name="Renamed")
    assert u1 is not None
    assert u1.name == "Renamed"
    assert u1.category_id == cat.id and u1.term == "Fall" and u1.student_group_id == grp.id

    # An explicit None clears all three (to NULL) — the names come back None too.
    u2 = await events.update(
        a.id, ev.id, category_id=None, term=None, student_group_id=None
    )
    assert u2 is not None
    assert u2.category_id is None and u2.category_name is None
    assert u2.term is None
    assert u2.student_group_id is None and u2.student_group_name is None

    # Re-setting from cleared works (a value sets it again).
    u3 = await events.update(a.id, ev.id, category_id=cat.id)
    assert u3 is not None
    assert u3.category_id == cat.id and u3.category_name == "Sports"
    assert u3.term is None  # the still-omitted term stays cleared
