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
from backend.adapters.repositories.postgres_schools import PostgresSchoolRepository
from backend.adapters.repositories.postgres_users import PostgresUserRepository
from backend.db.base import Base
from backend.db.session import make_engine, make_sessionmaker
from backend.domain.errors import ConflictError, NotFoundError
from backend.domain.models import Role
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_DSN = os.environ.get("BE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(_DSN is None, reason="BE_TEST_DATABASE_URL not set")


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
