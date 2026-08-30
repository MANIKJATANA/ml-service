"""OnboardingService use-cases with fakes (decisions/0025, BP7c)."""

from __future__ import annotations

import pytest
from backend.domain.errors import (
    ConflictError,
    LimitExceededError,
    NotFoundError,
    ValidationError,
)
from backend.domain.models import Role, School, SchoolStatus, User, UserStatus
from backend.services.onboarding_service import OnboardingService
from backend_fakes import (
    FakeAdminActionAuditRepo,
    FakeEventCategoryRepo,
    FakeHasher,
    FakeSchoolRepo,
    FakeUserRepo,
    make_school,
    make_user,
)


def _svc(
    *, schools: list[School] | None = None, users: list[User] | None = None
) -> tuple[OnboardingService, FakeSchoolRepo, FakeUserRepo]:
    srepo = FakeSchoolRepo(schools or [])
    urepo = FakeUserRepo(users or [])
    return (
        OnboardingService(
            srepo, urepo, FakeHasher(), FakeEventCategoryRepo(), FakeAdminActionAuditRepo()
        ),
        srepo,
        urepo,
    )


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


# ---- update-school (BP18c) ---------------------------------------------


async def test_update_school_renames_and_changes_cap() -> None:
    svc, srepo, _ = _svc(schools=[make_school(id="s1", name="Old", max_teachers=5)])
    updated = await svc.update_school(school_id="s1", name="  New Name ", max_teachers=20)
    assert updated.name == "New Name" and updated.max_teachers == 20  # trimmed
    stored = await srepo.get("s1")
    assert stored is not None and stored.name == "New Name" and stored.max_teachers == 20


async def test_update_school_suspends_and_reactivates() -> None:
    svc, _, _ = _svc(schools=[make_school(id="s1")])
    suspended = await svc.update_school(school_id="s1", status=SchoolStatus.SUSPENDED)
    assert suspended.status is SchoolStatus.SUSPENDED
    active = await svc.update_school(school_id="s1", status=SchoolStatus.ACTIVE)
    assert active.status is SchoolStatus.ACTIVE


async def test_update_school_partial_leaves_other_fields() -> None:
    svc, _, _ = _svc(schools=[make_school(id="s1", name="Keep", max_teachers=7)])
    updated = await svc.update_school(school_id="s1", status=SchoolStatus.SUSPENDED)
    assert updated.name == "Keep" and updated.max_teachers == 7  # only status changed


async def test_update_school_missing_is_404() -> None:
    svc, _, _ = _svc(schools=[])
    with pytest.raises(NotFoundError):
        await svc.update_school(school_id="nope", name="X")


async def test_update_school_rejects_bad_input() -> None:
    svc, _, _ = _svc(schools=[make_school(id="s1")])
    with pytest.raises(ValidationError):
        await svc.update_school(school_id="s1", name="   ")  # empty after strip
    with pytest.raises(ValidationError):
        await svc.update_school(school_id="s1", max_teachers=0)


async def test_create_school_admin_provisions_temp_password_account() -> None:
    svc, _, _ = _svc(schools=[make_school(id="s1", max_teachers=1)])
    prov = await svc.create_school_admin(school_id="s1", email="Admin@X.io")
    assert prov.user.role is Role.SCHOOL_ADMIN and prov.user.school_id == "s1"
    assert prov.user.must_change_password is True
    assert prov.user.email == "admin@x.io"  # normalized
    # A server-generated temp password (BP7c), returned once + hashed (never the raw pw).
    assert len(prov.temp_password) >= 8
    assert prov.user.password_hash == f"hash:{prov.temp_password}"


async def test_create_teacher_generates_a_distinct_temp_password_each_time() -> None:
    svc, _, _ = _svc(schools=[make_school(id="s1", max_teachers=5)])
    a = await svc.create_teacher(school_id="s1", email="a@x.io")
    b = await svc.create_teacher(school_id="s1", email="b@x.io")
    assert a.temp_password and b.temp_password
    assert a.temp_password != b.temp_password  # random per account


async def test_create_school_admin_for_missing_school() -> None:
    svc, _, _ = _svc()
    with pytest.raises(NotFoundError):
        await svc.create_school_admin(school_id="nope", email="a@x.io")


async def test_create_teacher_enforces_cap() -> None:
    svc, _, _ = _svc(schools=[make_school(id="s1", max_teachers=1)])
    t1 = await svc.create_teacher(school_id="s1", email="t1@x.io")
    assert t1.user.role is Role.TEACHER and t1.user.must_change_password is True
    with pytest.raises(LimitExceededError):
        await svc.create_teacher(school_id="s1", email="t2@x.io")


async def test_cap_counts_teachers_only_not_admins() -> None:
    # An admin account must not consume a teacher slot (0025).
    svc, _, _ = _svc(schools=[make_school(id="s1", max_teachers=1)])
    await svc.create_school_admin(school_id="s1", email="a@x.io")
    t1 = await svc.create_teacher(school_id="s1", email="t1@x.io")
    assert t1.user.role is Role.TEACHER
    with pytest.raises(LimitExceededError):
        await svc.create_teacher(school_id="s1", email="t2@x.io")


async def test_create_teacher_rejected_when_cap_is_zero() -> None:
    # max_teachers=0 can exist on a pre-existing/edited school (schema ge=1 only
    # guards creation); every teacher creation must then be rejected (0025).
    svc, _, _ = _svc(schools=[make_school(id="s1", max_teachers=0)])
    with pytest.raises(LimitExceededError):
        await svc.create_teacher(school_id="s1", email="t@x.io")


async def test_email_is_globally_unique_across_schools() -> None:
    # uq_users_email is global (not per-school); the fake mirrors it.
    svc, _, _ = _svc(
        schools=[make_school(id="s1", max_teachers=5), make_school(id="s2", max_teachers=5)]
    )
    await svc.create_teacher(school_id="s1", email="t@x.io")
    with pytest.raises(ConflictError):
        await svc.create_teacher(school_id="s2", email="t@x.io")


async def test_school_admin_provisioning_ignores_cap_and_suspension() -> None:
    # Admins are neither capped nor blocked by suspension (unlike teachers, 0025).
    svc, _, _ = _svc(
        schools=[
            make_school(id="s1", max_teachers=1, status=SchoolStatus.SUSPENDED),
        ]
    )
    a1 = await svc.create_school_admin(school_id="s1", email="a1@x.io")
    a2 = await svc.create_school_admin(school_id="s1", email="a2@x.io")
    assert a1.user.role is Role.SCHOOL_ADMIN and a2.user.role is Role.SCHOOL_ADMIN


async def test_create_teacher_rejected_for_suspended_school() -> None:
    svc, _, _ = _svc(
        schools=[make_school(id="s1", max_teachers=5, status=SchoolStatus.SUSPENDED)]
    )
    with pytest.raises(ValidationError):
        await svc.create_teacher(school_id="s1", email="t@x.io")


async def test_create_teacher_for_missing_school() -> None:
    svc, _, _ = _svc()
    with pytest.raises(NotFoundError):
        await svc.create_teacher(school_id="nope", email="t@x.io")


async def test_list_staff_returns_only_teachers() -> None:
    svc, _, _ = _svc(schools=[make_school(id="s1", max_teachers=5)])
    await svc.create_school_admin(school_id="s1", email="a@x.io")
    await svc.create_teacher(school_id="s1", email="t1@x.io")
    await svc.create_teacher(school_id="s1", email="t2@x.io")
    staff = await svc.list_staff(school_id="s1")
    assert {u.email for u in staff} == {"t1@x.io", "t2@x.io"}
    assert all(u.role is Role.TEACHER for u in staff)


async def test_duplicate_email_conflicts_case_insensitively() -> None:
    svc, _, _ = _svc(schools=[make_school(id="s1", max_teachers=5)])
    await svc.create_teacher(school_id="s1", email="t@x.io")
    with pytest.raises(ConflictError):
        await svc.create_teacher(school_id="s1", email="T@X.io")


# ---- staff lifecycle: disable / enable (BP7c) --------------------------


async def test_set_staff_status_disables_then_enables_a_teacher() -> None:
    teacher = make_user(id="t1", school_id="s1", email="t@x.io", role=Role.TEACHER)
    svc, _, urepo = _svc(
        schools=[make_school(id="s1", max_teachers=5)], users=[teacher]
    )
    disabled = await svc.set_staff_status(
        school_id="s1", user_id="t1", role=Role.TEACHER, status=UserStatus.DISABLED
    )
    assert disabled.status is UserStatus.DISABLED
    stored = await urepo.get("t1")
    assert stored is not None and stored.status is UserStatus.DISABLED

    enabled = await svc.set_staff_status(
        school_id="s1", user_id="t1", role=Role.TEACHER, status=UserStatus.ACTIVE
    )
    assert enabled.status is UserStatus.ACTIVE


async def test_set_status_is_idempotent() -> None:
    teacher = make_user(id="t1", school_id="s1", email="t@x.io", role=Role.TEACHER,
                        status=UserStatus.DISABLED)
    svc, _, _ = _svc(schools=[make_school(id="s1")], users=[teacher])
    again = await svc.set_staff_status(
        school_id="s1", user_id="t1", role=Role.TEACHER, status=UserStatus.DISABLED
    )
    assert again.status is UserStatus.DISABLED


async def test_set_status_rejects_a_teacher_in_another_school() -> None:
    # Tenant guard: s1's admin can't disable s2's teacher (404, no existence leak).
    other = make_user(id="t2", school_id="s2", email="t2@x.io", role=Role.TEACHER)
    svc, _, _ = _svc(schools=[make_school(id="s1")], users=[other])
    with pytest.raises(NotFoundError):
        await svc.set_staff_status(
            school_id="s1", user_id="t2", role=Role.TEACHER, status=UserStatus.DISABLED
        )


async def test_set_status_rejects_the_wrong_role() -> None:
    # Role guard: the /staff route (role=TEACHER) can't touch an admin, and vice versa.
    admin = make_user(id="a1", school_id="s1", email="a@x.io", role=Role.SCHOOL_ADMIN)
    svc, _, _ = _svc(schools=[make_school(id="s1")], users=[admin])
    with pytest.raises(NotFoundError):
        await svc.set_staff_status(
            school_id="s1", user_id="a1", role=Role.TEACHER, status=UserStatus.DISABLED
        )


# ---- last-admin guard (BP18b) ------------------------------------------


async def test_cannot_disable_the_last_active_admin() -> None:
    # BP18b: disabling a school's only active admin is refused — it would lock everyone out
    # of managing the school. The row is left untouched.
    admin = make_user(id="a1", school_id="s1", email="a@x.io", role=Role.SCHOOL_ADMIN)
    svc, _, urepo = _svc(schools=[make_school(id="s1")], users=[admin])
    with pytest.raises(ValidationError):
        await svc.set_staff_status(
            school_id="s1", user_id="a1", role=Role.SCHOOL_ADMIN, status=UserStatus.DISABLED
        )
    stored = await urepo.get("a1")
    assert stored is not None and stored.status is UserStatus.ACTIVE  # unchanged


async def test_can_disable_an_admin_when_another_active_one_remains() -> None:
    a1 = make_user(id="a1", school_id="s1", email="a1@x.io", role=Role.SCHOOL_ADMIN)
    a2 = make_user(id="a2", school_id="s1", email="a2@x.io", role=Role.SCHOOL_ADMIN)
    svc, _, _ = _svc(schools=[make_school(id="s1")], users=[a1, a2])
    result = await svc.set_staff_status(
        school_id="s1", user_id="a1", role=Role.SCHOOL_ADMIN, status=UserStatus.DISABLED
    )
    assert result.status is UserStatus.DISABLED


async def test_a_disabled_second_admin_does_not_count_as_active() -> None:
    # Only ACTIVE admins keep the school manageable: with one active + one already-disabled
    # admin, disabling the active one is still refused (it's the last ACTIVE one).
    a1 = make_user(id="a1", school_id="s1", email="a1@x.io", role=Role.SCHOOL_ADMIN)
    a2 = make_user(
        id="a2", school_id="s1", email="a2@x.io", role=Role.SCHOOL_ADMIN,
        status=UserStatus.DISABLED,
    )
    svc, _, _ = _svc(schools=[make_school(id="s1")], users=[a1, a2])
    with pytest.raises(ValidationError):
        await svc.set_staff_status(
            school_id="s1", user_id="a1", role=Role.SCHOOL_ADMIN, status=UserStatus.DISABLED
        )


async def test_reenabling_the_sole_admin_is_never_blocked() -> None:
    # The guard is one-directional — it only blocks disabling, never enabling.
    admin = make_user(
        id="a1", school_id="s1", email="a@x.io", role=Role.SCHOOL_ADMIN,
        status=UserStatus.DISABLED,
    )
    svc, _, _ = _svc(schools=[make_school(id="s1")], users=[admin])
    result = await svc.set_staff_status(
        school_id="s1", user_id="a1", role=Role.SCHOOL_ADMIN, status=UserStatus.ACTIVE
    )
    assert result.status is UserStatus.ACTIVE


async def test_last_teacher_disable_is_not_blocked() -> None:
    # Only the admin path is guarded — a lone teacher going dark locks no one out.
    teacher = make_user(id="t1", school_id="s1", email="t@x.io", role=Role.TEACHER)
    svc, _, _ = _svc(schools=[make_school(id="s1")], users=[teacher])
    result = await svc.set_staff_status(
        school_id="s1", user_id="t1", role=Role.TEACHER, status=UserStatus.DISABLED
    )
    assert result.status is UserStatus.DISABLED


# ---- resend-invite (BP7c) ----------------------------------------------


async def test_resend_invite_regenerates_temp_password_and_forces_change() -> None:
    teacher = make_user(id="t1", school_id="s1", email="t@x.io", role=Role.TEACHER,
                        password_hash="hash:old", must_change_password=False)
    svc, _, urepo = _svc(schools=[make_school(id="s1")], users=[teacher])
    prov = await svc.resend_invite(school_id="s1", user_id="t1", role=Role.TEACHER)
    assert len(prov.temp_password) >= 8
    assert prov.user.must_change_password is True
    # The stored hash is the NEW temp password's hash (not the old one).
    stored = await urepo.get("t1")
    assert stored is not None
    assert stored.password_hash == f"hash:{prov.temp_password}"
    assert stored.password_hash != "hash:old"


async def test_resend_invite_works_on_a_disabled_account_without_re_enabling() -> None:
    # A disabled teacher can be re-invited (regenerates a temp password) but stays
    # disabled — enabling is a separate, explicit action (BP7c).
    teacher = make_user(id="t1", school_id="s1", email="t@x.io", role=Role.TEACHER,
                        status=UserStatus.DISABLED)
    svc, _, urepo = _svc(schools=[make_school(id="s1")], users=[teacher])
    prov = await svc.resend_invite(school_id="s1", user_id="t1", role=Role.TEACHER)
    assert len(prov.temp_password) >= 8
    stored = await urepo.get("t1")
    assert stored is not None and stored.status is UserStatus.DISABLED


async def test_resend_invite_rejects_foreign_school_or_wrong_role() -> None:
    other = make_user(id="t2", school_id="s2", email="t2@x.io", role=Role.TEACHER)
    admin = make_user(id="a1", school_id="s1", email="a@x.io", role=Role.SCHOOL_ADMIN)
    svc, _, _ = _svc(schools=[make_school(id="s1")], users=[other, admin])
    with pytest.raises(NotFoundError):  # foreign school
        await svc.resend_invite(school_id="s1", user_id="t2", role=Role.TEACHER)
    with pytest.raises(NotFoundError):  # wrong role via the teacher route
        await svc.resend_invite(school_id="s1", user_id="a1", role=Role.TEACHER)
