"""OnboardingService use-cases with fakes (decisions/0025)."""

from __future__ import annotations

import pytest
from backend.domain.errors import (
    ConflictError,
    LimitExceededError,
    NotFoundError,
    ValidationError,
)
from backend.domain.models import Role, School, SchoolStatus, User
from backend.services.onboarding_service import OnboardingService
from backend_fakes import FakeHasher, FakeSchoolRepo, FakeUserRepo, make_school

_PW = "temp-pw-123"


def _svc(
    *, schools: list[School] | None = None, users: list[User] | None = None
) -> tuple[OnboardingService, FakeSchoolRepo, FakeUserRepo]:
    srepo = FakeSchoolRepo(schools or [])
    urepo = FakeUserRepo(users or [])
    return OnboardingService(srepo, urepo, FakeHasher()), srepo, urepo


async def test_create_school_trims_validates_and_persists() -> None:
    svc, _, _ = _svc()
    school = await svc.create_school(name="  Springfield ", max_teachers=3)
    assert school.name == "Springfield" and school.max_teachers == 3
    assert school.status is SchoolStatus.ACTIVE


async def test_create_school_rejects_bad_input() -> None:
    svc, _, _ = _svc()
    with pytest.raises(ValidationError):
        await svc.create_school(name="   ", max_teachers=3)
    with pytest.raises(ValidationError):
        await svc.create_school(name="X", max_teachers=0)


async def test_get_school_missing_raises() -> None:
    svc, _, _ = _svc()
    with pytest.raises(NotFoundError):
        await svc.get_school("nope")


async def test_list_schools() -> None:
    svc, _, _ = _svc()
    await svc.create_school(name="A", max_teachers=1)
    await svc.create_school(name="B", max_teachers=1)
    assert len(await svc.list_schools()) == 2


async def test_create_school_admin_provisions_temp_password_account() -> None:
    svc, _, _ = _svc(schools=[make_school(id="s1", max_teachers=1)])
    admin = await svc.create_school_admin(school_id="s1", email="Admin@X.io", password=_PW)
    assert admin.role is Role.SCHOOL_ADMIN and admin.school_id == "s1"
    assert admin.must_change_password is True
    assert admin.email == "admin@x.io"  # normalized
    assert admin.password_hash == f"hash:{_PW}"  # hashed, never the raw password


async def test_create_school_admin_for_missing_school() -> None:
    svc, _, _ = _svc()
    with pytest.raises(NotFoundError):
        await svc.create_school_admin(school_id="nope", email="a@x.io", password=_PW)


async def test_create_teacher_enforces_cap() -> None:
    svc, _, _ = _svc(schools=[make_school(id="s1", max_teachers=1)])
    t1 = await svc.create_teacher(school_id="s1", email="t1@x.io", password=_PW)
    assert t1.role is Role.TEACHER and t1.must_change_password is True
    with pytest.raises(LimitExceededError):
        await svc.create_teacher(school_id="s1", email="t2@x.io", password=_PW)


async def test_cap_counts_teachers_only_not_admins() -> None:
    # An admin account must not consume a teacher slot (0025).
    svc, _, _ = _svc(schools=[make_school(id="s1", max_teachers=1)])
    await svc.create_school_admin(school_id="s1", email="a@x.io", password=_PW)
    t1 = await svc.create_teacher(school_id="s1", email="t1@x.io", password=_PW)
    assert t1.role is Role.TEACHER
    with pytest.raises(LimitExceededError):
        await svc.create_teacher(school_id="s1", email="t2@x.io", password=_PW)


async def test_create_teacher_rejected_when_cap_is_zero() -> None:
    # max_teachers=0 can exist on a pre-existing/edited school (schema ge=1 only
    # guards creation); every teacher creation must then be rejected (0025).
    svc, _, _ = _svc(schools=[make_school(id="s1", max_teachers=0)])
    with pytest.raises(LimitExceededError):
        await svc.create_teacher(school_id="s1", email="t@x.io", password=_PW)


async def test_email_is_globally_unique_across_schools() -> None:
    # uq_users_email is global (not per-school); the fake mirrors it.
    svc, _, _ = _svc(
        schools=[make_school(id="s1", max_teachers=5), make_school(id="s2", max_teachers=5)]
    )
    await svc.create_teacher(school_id="s1", email="t@x.io", password=_PW)
    with pytest.raises(ConflictError):
        await svc.create_teacher(school_id="s2", email="t@x.io", password=_PW)


async def test_school_admin_provisioning_ignores_cap_and_suspension() -> None:
    # Admins are neither capped nor blocked by suspension (unlike teachers, 0025).
    svc, _, _ = _svc(
        schools=[
            make_school(id="s1", max_teachers=1, status=SchoolStatus.SUSPENDED),
        ]
    )
    a1 = await svc.create_school_admin(school_id="s1", email="a1@x.io", password=_PW)
    a2 = await svc.create_school_admin(school_id="s1", email="a2@x.io", password=_PW)
    assert a1.role is Role.SCHOOL_ADMIN and a2.role is Role.SCHOOL_ADMIN


async def test_create_teacher_rejected_for_suspended_school() -> None:
    svc, _, _ = _svc(
        schools=[make_school(id="s1", max_teachers=5, status=SchoolStatus.SUSPENDED)]
    )
    with pytest.raises(ValidationError):
        await svc.create_teacher(school_id="s1", email="t@x.io", password=_PW)


async def test_create_teacher_for_missing_school() -> None:
    svc, _, _ = _svc()
    with pytest.raises(NotFoundError):
        await svc.create_teacher(school_id="nope", email="t@x.io", password=_PW)


async def test_list_staff_returns_only_teachers() -> None:
    svc, _, _ = _svc(schools=[make_school(id="s1", max_teachers=5)])
    await svc.create_school_admin(school_id="s1", email="a@x.io", password=_PW)
    await svc.create_teacher(school_id="s1", email="t1@x.io", password=_PW)
    await svc.create_teacher(school_id="s1", email="t2@x.io", password=_PW)
    staff = await svc.list_staff(school_id="s1")
    assert {u.email for u in staff} == {"t1@x.io", "t2@x.io"}
    assert all(u.role is Role.TEACHER for u in staff)


async def test_duplicate_email_conflicts_case_insensitively() -> None:
    svc, _, _ = _svc(schools=[make_school(id="s1", max_teachers=5)])
    await svc.create_teacher(school_id="s1", email="t@x.io", password=_PW)
    with pytest.raises(ConflictError):
        await svc.create_teacher(school_id="s1", email="T@X.io", password=_PW)
