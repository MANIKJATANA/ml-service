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

import pytest
from backend.adapters.repositories.postgres_events import PostgresEventRepository
from backend.adapters.repositories.postgres_match_corrections import (
    PostgresMatchCorrectionRepository,
)
from backend.adapters.repositories.postgres_media import PostgresMediaRepository
from backend.adapters.repositories.postgres_notification_reads import (
    PostgresNotificationReadRepository,
)
from backend.adapters.repositories.postgres_schools import PostgresSchoolRepository
from backend.adapters.repositories.postgres_students import PostgresStudentRepository
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
    UserStatus,
)
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
    await users.set_password(temp.id, password_hash="h2-new", must_change_password=False)
    reloaded = await users.get(temp.id)
    assert reloaded is not None
    assert reloaded.password_hash == "h2-new"
    assert reloaded.must_change_password is False

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

    e1 = await mk(a.id, "not_started+media")  # active, not_started, has media
    await mk(a.id, "not_started, no media")  # active, not_started, no media
    e3 = await mk(a.id, "processing")  # active, processing, has media
    e4 = await mk(a.id, "archived+completed")  # archived, completed
    e5 = await mk(a.id, "archived not_started+media")  # archived, not_started, has media
    await mk(b.id, "B-noise")  # other school

    await events.set_processing(e3, status=EventProcessingStatus.PROCESSING)
    await events.update(a.id, e4, status=EventStatus.ARCHIVED)
    await events.set_processing(e4, status=EventProcessingStatus.COMPLETED)
    await events.update(a.id, e5, status=EventStatus.ARCHIVED)

    for ev_id, path in ((e1, "p1.jpg"), (e3, "p3.jpg"), (e5, "p5.jpg")):
        await media.create(
            school_id=a.id, event_id=ev_id, storage_path=path,
            media_type=MediaType.IMAGE,
        )

    rollup = await events.status_counts(a.id)
    # 5 events: e1/e2/e3 active, e4/e5 archived; only e3 in-flight.
    assert (rollup.total, rollup.active, rollup.archived, rollup.processing) == (
        5, 3, 2, 1,
    )

    # Only e1 is active AND not_started AND has ≥1 photo. e5 is not_started with media
    # but ARCHIVED (can't be Processed), so it's excluded; e3 isn't not_started.
    assert await events.count_not_started_with_media(a.id) == 1
    assert await events.count_not_started_with_media("not-a-uuid") == 0

    # count_distributed (BP7a): "announced" = a manual notified_at OR (auto_notify —
    # server-defaults true — AND completed_at). e4 is ARCHIVED + completed -> still
    # announced via the auto path (distribution is status-agnostic); mark e1 notified too.
    # e2/e3/e5 are neither completed nor notified -> excluded.
    await events.mark_notified(e1)
    assert await events.count_distributed(a.id) == 2
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
