"""Admin-action audit — the governance actor trail (BP28b, R4-A25).

Three layers:
  * AdminActionAuditService reads — composition (actor email join, deleted-actor None), tenant
    scoping, pagination newest-first, each filter.
  * Write-hooks — each hooked governance mutation records exactly one row with the right
    action/target_type/target_label/actor_role; an idempotent no-op records nothing; a bulk
    loop records one row per target; a raising audit repo never fails the mutation;
    delete_student records id-only (no name/email); update_school records school_id=target +
    actor_role=platform_admin.
  * Route — GET /v1/audit/actions: the audit:view matrix (admin 200 / teacher 403 / student
    403 / unauth 401), tenant isolation, filters, pagination.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.domain.models import (
    AdminAction,
    AdminActionAuditEntry,
    AdminActionTargetType,
    Role,
    SchoolStatus,
    User,
    UserStatus,
)
from backend.main import create_app
from backend.services.admin_action_audit_service import AdminActionAuditService
from backend.services.onboarding_service import OnboardingService
from backend.services.student_service import StudentService
from backend_fakes import (
    FakeAdminActionAuditRepo,
    FakeEventCategoryRepo,
    FakeHasher,
    FakeMlClient,
    FakeObjectStore,
    FakeSchoolRepo,
    FakeStudentGroupRepo,
    FakeStudentRepo,
    FakeThumbnailer,
    FakeUserRepo,
    SeededContainer,
    make_admin_action_audit_entry,
    make_school,
    make_student,
    make_user,
)
from fastapi.testclient import TestClient

_S1 = "s1"
_HASHER = Argon2PasswordHasher()
_PATH = "reference-photos/s1/photo.jpg"


def _t(second: int) -> datetime:
    return datetime(2026, 1, 1, 0, 0, second, tzinfo=UTC)


# ======================================================================
# 1. AdminActionAuditService (reads)
# ======================================================================


def _svc(
    *,
    entries: list[AdminActionAuditEntry] | None = None,
    users: list[User] | None = None,
) -> AdminActionAuditService:
    return AdminActionAuditService(
        FakeAdminActionAuditRepo(entries or []), FakeUserRepo(users or [])
    )


async def test_log_composes_actor_email_and_paginates_newest_first() -> None:
    svc = _svc(
        users=[
            make_user(id="sa", school_id=_S1, email="sa@x.io", role=Role.SCHOOL_ADMIN)
        ],
        entries=[
            make_admin_action_audit_entry(
                id=f"aa{n}", school_id=_S1, actor_user_id="sa",
                actor_role="school_admin", action="student_created",
                target_type="student", target_id=f"stu{n}",
                target_label=f"Kid {n}", created_at=_t(n),
            )
            for n in range(1, 6)  # aa1..aa5
        ],
    )
    page = await svc.school_action_log(school_id=_S1, limit=2, offset=0)
    assert page.total == 5 and page.limit == 2 and page.offset == 0
    assert [i.id for i in page.items] == ["aa5", "aa4"]  # newest-first
    assert page.items[0].actor_email == "sa@x.io"  # composed from the users row
    assert page.items[0].action == "student_created"
    assert page.items[0].target_label == "Kid 5"
    page2 = await svc.school_action_log(school_id=_S1, limit=2, offset=2)
    assert [i.id for i in page2.items] == ["aa3", "aa2"]


async def test_log_deleted_actor_reads_none_but_role_survives() -> None:
    # actor_user_id present but no matching users row (account deleted → FK SET NULL in prod);
    # here the users repo is empty, so the email can't be composed. The denormalized role stays.
    svc = _svc(
        users=[],
        entries=[
            make_admin_action_audit_entry(
                id="aa1", school_id=_S1, actor_user_id=None, actor_role="school_admin",
                action="student_deleted", target_type="student", target_id="stu1",
                target_label=None,
            )
        ],
    )
    page = await svc.school_action_log(school_id=_S1, limit=50, offset=0)
    item = page.items[0]
    assert item.actor_user_id is None and item.actor_email is None
    assert item.actor_role == "school_admin"  # survives the deletion
    assert item.target_label is None  # a deleted student keeps no identity (BP8e)


async def test_log_tenant_scoped_excludes_foreign_rows() -> None:
    svc = _svc(
        users=[make_user(id="u", school_id=_S1, role=Role.SCHOOL_ADMIN)],
        entries=[
            make_admin_action_audit_entry(id="mine", school_id=_S1, actor_user_id="u"),
            make_admin_action_audit_entry(
                id="theirs", school_id="other", actor_user_id="u"
            ),
        ],
    )
    page = await svc.school_action_log(school_id=_S1, limit=50, offset=0)
    assert [i.id for i in page.items] == ["mine"]


def _filter_svc() -> AdminActionAuditService:
    return _svc(
        users=[make_user(id="sa", school_id=_S1, role=Role.SCHOOL_ADMIN)],
        entries=[
            make_admin_action_audit_entry(
                id="c1", school_id=_S1, actor_user_id="sa", action="student_created",
                target_type="student", target_id="stu1", created_at=_t(1),
            ),
            make_admin_action_audit_entry(
                id="d1", school_id=_S1, actor_user_id="sa", action="student_disabled",
                target_type="student", target_id="stu1", created_at=_t(2),
            ),
            make_admin_action_audit_entry(
                id="s1", school_id=_S1, actor_user_id="sa", action="staff_created",
                target_type="staff", target_id="tt1", created_at=_t(3),
            ),
        ],
    )


async def test_log_filters_by_action() -> None:
    svc = _filter_svc()
    page = await svc.school_action_log(
        school_id=_S1, limit=50, offset=0, action="student_created"
    )
    assert page.total == 1 and [i.id for i in page.items] == ["c1"]


async def test_log_filters_by_target_type() -> None:
    svc = _filter_svc()
    page = await svc.school_action_log(
        school_id=_S1, limit=50, offset=0, target_type="staff"
    )
    assert page.total == 1 and [i.id for i in page.items] == ["s1"]


async def test_log_filters_by_target_id() -> None:
    svc = _filter_svc()
    page = await svc.school_action_log(
        school_id=_S1, limit=50, offset=0, target_id="stu1"
    )
    # c1 (created) + d1 (disabled) both target stu1, newest-first.
    assert page.total == 2 and [i.id for i in page.items] == ["d1", "c1"]


async def test_log_filters_by_actor_and_date_range() -> None:
    svc = _filter_svc()
    by_actor = await svc.school_action_log(
        school_id=_S1, limit=50, offset=0, actor_user_id="sa"
    )
    assert by_actor.total == 3
    windowed = await svc.school_action_log(
        school_id=_S1, limit=50, offset=0, created_from=_t(2), created_to=_t(3)
    )
    assert [i.id for i in windowed.items] == ["s1", "d1"]  # inclusive, newest-first


# ======================================================================
# 2. Write-hooks (through the real services)
# ======================================================================


def _student_svc(
    *,
    audit: FakeAdminActionAuditRepo | None = None,
    users: list[User] | None = None,
    ml_client: FakeMlClient | None = None,
    school_status: SchoolStatus = SchoolStatus.ACTIVE,
) -> tuple[StudentService, FakeStudentRepo, FakeUserRepo, FakeAdminActionAuditRepo]:
    school = make_school(id=_S1, max_teachers=5)
    if school_status is not SchoolStatus.ACTIVE:
        from dataclasses import replace

        school = replace(school, status=school_status)
    srepo = FakeSchoolRepo([school])
    urepo = FakeUserRepo(users or [])
    strepo = FakeStudentRepo()
    grepo = FakeStudentGroupRepo()
    aud = audit or FakeAdminActionAuditRepo()
    urepo.link_cascade(strepo.remove_by_user)
    strepo.link_users(urepo.email_of)
    strepo.link_user_status(urepo.status_of)
    strepo.link_groups(grepo.name_of)
    svc = StudentService(
        strepo,
        urepo,
        srepo,
        FakeHasher(),
        FakeObjectStore(),
        ml_client or FakeMlClient(),
        FakeThumbnailer(),
        grepo,
        aud,
        reference_photo_prefix="reference-photos",
    )
    return svc, strepo, urepo, aud


async def test_create_student_records_one_created_row() -> None:
    svc, _, _, aud = _student_svc()
    prov = await svc.create_student(
        school_id=_S1, name="Bart", email="bart@x.io",
        actor_user_id="sa", actor_role="school_admin",
    )
    assert len(aud.rows) == 1
    row = aud.rows[0]
    assert row.action == AdminAction.STUDENT_CREATED.value
    assert row.target_type == AdminActionTargetType.STUDENT.value
    assert row.target_id == prov.student.id
    assert row.target_label == "Bart"
    assert row.actor_user_id == "sa" and row.actor_role == "school_admin"
    assert row.school_id == _S1


async def test_set_status_disable_then_enable_records_two_rows() -> None:
    svc, _, _, aud = _student_svc()
    prov = await svc.create_student(
        school_id=_S1, name="Bart", email="bart@x.io",
        actor_user_id="sa", actor_role="school_admin",
    )
    aud._rows.clear()  # focus on the status changes
    await svc.set_status(
        school_id=_S1, student_id=prov.student.id, status=UserStatus.DISABLED,
        actor_user_id="sa", actor_role="school_admin",
    )
    await svc.set_status(
        school_id=_S1, student_id=prov.student.id, status=UserStatus.ACTIVE,
        actor_user_id="sa", actor_role="school_admin",
    )
    assert [r.action for r in aud.rows] == [
        AdminAction.STUDENT_DISABLED.value,
        AdminAction.STUDENT_ENABLED.value,
    ]
    assert all(r.target_label == "Bart" for r in aud.rows)


async def test_set_status_idempotent_no_op_records_nothing() -> None:
    # Setting the status a student already has must NOT record a row (the hook is inside the
    # `if student.status is not status` guard).
    svc, _, _, aud = _student_svc()
    prov = await svc.create_student(
        school_id=_S1, name="Bart", email="bart@x.io",
        actor_user_id="sa", actor_role="school_admin",
    )
    aud._rows.clear()
    # A fresh student is ACTIVE — re-setting ACTIVE is a no-op.
    await svc.set_status(
        school_id=_S1, student_id=prov.student.id, status=UserStatus.ACTIVE,
        actor_user_id="sa", actor_role="school_admin",
    )
    assert aud.rows == []


async def test_delete_student_records_deleted_with_id_only_label() -> None:
    # BP8e: the erased student's name/email must NOT linger — target_label is None, target_id
    # is the student id.
    svc, _, _, aud = _student_svc()
    prov = await svc.create_student(
        school_id=_S1, name="Bart", email="bart@x.io",
        actor_user_id="sa", actor_role="school_admin",
    )
    aud._rows.clear()
    await svc.delete_student(
        school_id=_S1, student_id=prov.student.id,
        actor_user_id="sa", actor_role="school_admin",
    )
    assert len(aud.rows) == 1
    row = aud.rows[0]
    assert row.action == AdminAction.STUDENT_DELETED.value
    assert row.target_id == prov.student.id
    assert row.target_label is None  # id-only, no name/email


async def test_reenroll_records_reenrolled() -> None:
    svc, _, _, aud = _student_svc()
    prov = await svc.create_student(
        school_id=_S1, name="Bart", email="bart@x.io", reference_photo_path=_PATH,
        actor_user_id="sa", actor_role="school_admin",
    )
    aud._rows.clear()
    await svc.enroll_student(
        school_id=_S1, student_id=prov.student.id,
        actor_user_id="sa", actor_role="school_admin",
    )
    assert [r.action for r in aud.rows] == [AdminAction.STUDENT_REENROLLED.value]
    assert aud.rows[0].target_label == "Bart"


async def test_set_reference_photo_records_reenrolled() -> None:
    svc, _, _, aud = _student_svc()
    prov = await svc.create_student(  # photoless
        school_id=_S1, name="Bart", email="bart@x.io",
        actor_user_id="sa", actor_role="school_admin",
    )
    aud._rows.clear()
    await svc.set_reference_photo(
        school_id=_S1, student_id=prov.student.id, reference_photo_path=_PATH,
        actor_user_id="sa", actor_role="school_admin",
    )
    assert [r.action for r in aud.rows] == [AdminAction.STUDENT_REENROLLED.value]


async def test_student_resend_invite_records_invite_resent() -> None:
    svc, _, _, aud = _student_svc()
    prov = await svc.create_student(
        school_id=_S1, name="Bart", email="bart@x.io",
        actor_user_id="sa", actor_role="school_admin",
    )
    aud._rows.clear()
    await svc.resend_invite(
        school_id=_S1, student_id=prov.student.id,
        actor_user_id="sa", actor_role="school_admin",
    )
    assert [r.action for r in aud.rows] == [AdminAction.STUDENT_INVITE_RESENT.value]


async def test_bulk_create_records_one_row_per_target() -> None:
    svc, _, _, aud = _student_svc()
    results = await svc.bulk_create_students(
        school_id=_S1,
        rows=[("Ann", "ann@x.io", None, None), ("Bob", "bob@x.io", None, None)],
        actor_user_id="sa", actor_role="school_admin",
    )
    assert [r.status for r in results] == ["created", "created"]
    # One student_created audit row per created student.
    created_rows = [r for r in aud.rows if r.action == AdminAction.STUDENT_CREATED.value]
    assert len(created_rows) == 2
    assert {r.target_label for r in created_rows} == {"Ann", "Bob"}


async def test_bulk_delete_records_one_row_per_target() -> None:
    svc, _, _, aud = _student_svc()
    p1 = await svc.create_student(
        school_id=_S1, name="Ann", email="ann@x.io",
        actor_user_id="sa", actor_role="school_admin",
    )
    p2 = await svc.create_student(
        school_id=_S1, name="Bob", email="bob@x.io",
        actor_user_id="sa", actor_role="school_admin",
    )
    aud._rows.clear()
    await svc.bulk_delete_students(
        school_id=_S1, student_ids=[p1.student.id, p2.student.id],
        actor_user_id="sa", actor_role="school_admin",
    )
    deleted = [r for r in aud.rows if r.action == AdminAction.STUDENT_DELETED.value]
    assert {r.target_id for r in deleted} == {p1.student.id, p2.student.id}
    assert all(r.target_label is None for r in deleted)  # id-only in bulk too


async def test_raising_audit_repo_never_fails_the_mutation() -> None:
    # A failed audit write must NOT fail the create (best-effort swallow).
    aud = FakeAdminActionAuditRepo(raise_on_record=RuntimeError("audit down"))
    svc, strepo, _, _ = _student_svc(audit=aud)
    prov = await svc.create_student(
        school_id=_S1, name="Bart", email="bart@x.io",
        actor_user_id="sa", actor_role="school_admin",
    )
    # The student was still created despite the audit blowing up.
    assert await strepo.get(_S1, prov.student.id) is not None
    assert aud.rows == []  # nothing recorded


# ---- OnboardingService hooks ------------------------------------------


def _onboarding_svc(
    *, users: list[User] | None = None, schools_status: SchoolStatus = SchoolStatus.ACTIVE
) -> tuple[OnboardingService, FakeSchoolRepo, FakeUserRepo, FakeAdminActionAuditRepo]:
    from dataclasses import replace

    school = make_school(id=_S1, max_teachers=5)
    if schools_status is not SchoolStatus.ACTIVE:
        school = replace(school, status=schools_status)
    srepo = FakeSchoolRepo([school])
    urepo = FakeUserRepo(users or [])
    aud = FakeAdminActionAuditRepo()
    svc = OnboardingService(srepo, urepo, FakeHasher(), FakeEventCategoryRepo(), aud)
    return svc, srepo, urepo, aud


async def test_create_teacher_records_staff_created_with_email_label() -> None:
    svc, _, _, aud = _onboarding_svc()
    prov = await svc.create_teacher(
        school_id=_S1, email="tt@x.io",
        actor_user_id="sa", actor_role="school_admin",
    )
    assert len(aud.rows) == 1
    row = aud.rows[0]
    assert row.action == AdminAction.STAFF_CREATED.value
    assert row.target_type == AdminActionTargetType.STAFF.value
    assert row.target_id == prov.user.id
    assert row.target_label == "tt@x.io"


async def test_create_school_admin_records_school_id_target() -> None:
    # A platform admin creates a school admin — the audit row's school_id is the TARGET school
    # (so that school's admin reads it), actor_role=platform_admin.
    svc, _, _, aud = _onboarding_svc()
    await svc.create_school_admin(
        school_id=_S1, email="admin@x.io",
        actor_user_id="pa", actor_role="platform_admin",
    )
    assert len(aud.rows) == 1
    assert aud.rows[0].school_id == _S1
    assert aud.rows[0].actor_role == "platform_admin"
    assert aud.rows[0].action == AdminAction.STAFF_CREATED.value


async def test_set_staff_status_records_enabled_disabled() -> None:
    teacher = make_user(id="tt", school_id=_S1, email="tt@x.io", role=Role.TEACHER)
    svc, _, _, aud = _onboarding_svc(users=[teacher])
    await svc.set_staff_status(
        school_id=_S1, user_id="tt", role=Role.TEACHER, status=UserStatus.DISABLED,
        actor_user_id="sa", actor_role="school_admin",
    )
    assert [r.action for r in aud.rows] == [AdminAction.STAFF_DISABLED.value]
    assert aud.rows[0].target_label == "tt@x.io"


async def test_set_staff_status_no_op_records_nothing() -> None:
    # An already-active teacher re-set active is a no-op → no row.
    teacher = make_user(
        id="tt", school_id=_S1, email="tt@x.io", role=Role.TEACHER,
        status=UserStatus.ACTIVE,
    )
    svc, _, _, aud = _onboarding_svc(users=[teacher])
    await svc.set_staff_status(
        school_id=_S1, user_id="tt", role=Role.TEACHER, status=UserStatus.ACTIVE,
        actor_user_id="sa", actor_role="school_admin",
    )
    assert aud.rows == []


async def test_blocked_last_admin_disable_records_nothing() -> None:
    # Disabling the only active admin is refused (BP18b) → the hook (past the guard) never runs.
    from backend.domain.errors import ValidationError

    admin = make_user(
        id="a1", school_id=_S1, email="a1@x.io", role=Role.SCHOOL_ADMIN,
        status=UserStatus.ACTIVE,
    )
    svc, _, _, aud = _onboarding_svc(users=[admin])
    with pytest.raises(ValidationError):
        await svc.set_staff_status(
            school_id=_S1, user_id="a1", role=Role.SCHOOL_ADMIN,
            status=UserStatus.DISABLED,
            actor_user_id="pa", actor_role="platform_admin",
        )
    assert aud.rows == []  # a blocked disable records nothing


async def test_staff_resend_invite_records_invite_resent() -> None:
    teacher = make_user(id="tt", school_id=_S1, email="tt@x.io", role=Role.TEACHER)
    svc, _, _, aud = _onboarding_svc(users=[teacher])
    await svc.resend_invite(
        school_id=_S1, user_id="tt", role=Role.TEACHER,
        actor_user_id="sa", actor_role="school_admin",
    )
    assert [r.action for r in aud.rows] == [AdminAction.STAFF_INVITE_RESENT.value]
    assert aud.rows[0].target_label == "tt@x.io"


async def test_update_school_records_school_target_and_platform_role() -> None:
    # The flagship special case: the actor is a platform_admin (school_id=None), so the audit
    # row's school_id MUST be the TARGET school, actor_role=platform_admin, target_type=school.
    svc, _, _, aud = _onboarding_svc()
    await svc.update_school(
        school_id=_S1, name="Renamed",
        actor_user_id="pa", actor_role="platform_admin",
    )
    assert len(aud.rows) == 1
    row = aud.rows[0]
    assert row.action == AdminAction.SCHOOL_UPDATED.value
    assert row.target_type == AdminActionTargetType.SCHOOL.value
    assert row.school_id == _S1  # the target school, NOT the (null) actor school
    assert row.target_id == _S1
    assert row.target_label == "Renamed"
    assert row.actor_role == "platform_admin"


async def test_bulk_create_staff_records_one_row_per_created() -> None:
    svc, _, _, aud = _onboarding_svc()
    results = await svc.bulk_create_staff(
        school_id=_S1, emails=["a@x.io", "b@x.io"],
        actor_user_id="sa", actor_role="school_admin",
    )
    assert [r.status for r in results] == ["created", "created"]
    created = [r for r in aud.rows if r.action == AdminAction.STAFF_CREATED.value]
    assert {r.target_label for r in created} == {"a@x.io", "b@x.io"}


# ======================================================================
# 3. Route: GET /v1/audit/actions
# ======================================================================


def _route_user(*, id: str, role: Role, school_id: str | None, email: str) -> User:
    user: User = make_user(
        id=id, school_id=school_id, email=email,
        password_hash=_HASHER.hash("pw"), role=role,
    )
    return user


def _build_route(
    *,
    audit: FakeAdminActionAuditRepo | None = None,
    students: FakeStudentRepo | None = None,
) -> TestClient:
    container = SeededContainer(
        FakeUserRepo(
            [
                _route_user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1", email="sa@x.io"),
                _route_user(id="tt", role=Role.TEACHER, school_id="s1", email="tt@x.io"),
                _route_user(id="stu", role=Role.STUDENT, school_id="s1", email="stu@x.io"),
            ]
        ),
        FakeSchoolRepo([make_school(id="s1")]),
        students=students or FakeStudentRepo(
            [make_student(id="st1", school_id="s1", user_id="stu", name="Bart")]
        ),
        admin_action_audit=audit,
    )
    app = create_app()
    app.dependency_overrides[get_container_dep] = lambda: container
    return TestClient(app)


def _token(client: TestClient, who: str) -> str:
    resp = client.post("/v1/auth/login", json={"email": f"{who}@x.io", "password": "pw"})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def _auth(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


def test_admin_can_read_action_log() -> None:
    client = _build_route()
    resp = client.get("/v1/audit/actions", headers=_auth(_token(client, "sa")))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {"items", "total", "limit", "offset"} <= body.keys()


def test_teacher_is_forbidden() -> None:
    client = _build_route()
    assert (
        client.get("/v1/audit/actions", headers=_auth(_token(client, "tt"))).status_code
        == 403
    )


def test_student_is_forbidden() -> None:
    client = _build_route()
    assert (
        client.get("/v1/audit/actions", headers=_auth(_token(client, "stu"))).status_code
        == 403
    )


def test_unauthenticated_is_401() -> None:
    client = _build_route()
    assert client.get("/v1/audit/actions").status_code == 401


def test_action_log_tenant_scoped_never_leaks_other_school() -> None:
    # A row from another school must never appear in this school's log.
    audit = FakeAdminActionAuditRepo(
        [
            make_admin_action_audit_entry(id="mine", school_id="s1", actor_user_id="sa"),
            make_admin_action_audit_entry(
                id="theirs", school_id="other", actor_user_id="sa"
            ),
        ]
    )
    client = _build_route(audit=audit)
    body = client.get("/v1/audit/actions", headers=_auth(_token(client, "sa"))).json()
    assert body["total"] == 1
    assert [i["id"] for i in body["items"]] == ["mine"]


def test_action_log_end_to_end_records_and_reads() -> None:
    # A real governance action through the student route shows up in the action log.
    client = _build_route()
    sa = _auth(_token(client, "sa"))
    # Create a student (mints a student_created row via the real StudentService hook).
    created = client.post(
        "/v1/students", headers=sa, json={"name": "Lisa", "email": "lisa@x.io"}
    )
    assert created.status_code == 201, created.text
    log = client.get("/v1/audit/actions", headers=sa).json()
    assert log["total"] >= 1
    top = log["items"][0]
    assert top["action"] == "student_created"
    assert top["target_label"] == "Lisa"
    assert top["actor_email"] == "sa@x.io"
    assert top["actor_role"] == "school_admin"


def test_action_log_filters_and_pagination() -> None:
    rows = [
        make_admin_action_audit_entry(
            id="c1", school_id="s1", actor_user_id="sa", action="student_created",
            target_type="student", target_id="st1", created_at=_t(1),
        ),
        make_admin_action_audit_entry(
            id="d1", school_id="s1", actor_user_id="sa", action="student_disabled",
            target_type="student", target_id="st1", created_at=_t(2),
        ),
        make_admin_action_audit_entry(
            id="s1r", school_id="s1", actor_user_id="sa", action="staff_created",
            target_type="staff", target_id="tt1", created_at=_t(3),
        ),
    ]
    client = _build_route(audit=FakeAdminActionAuditRepo(rows))
    sa = _auth(_token(client, "sa"))
    # action filter.
    by_action = client.get(
        "/v1/audit/actions?action=student_created", headers=sa
    ).json()
    assert by_action["total"] == 1 and by_action["items"][0]["id"] == "c1"
    # target_type filter.
    by_type = client.get("/v1/audit/actions?target_type=staff", headers=sa).json()
    assert by_type["total"] == 1 and by_type["items"][0]["id"] == "s1r"
    # pagination (newest-first).
    p1 = client.get("/v1/audit/actions?limit=1&offset=0", headers=sa).json()
    p2 = client.get("/v1/audit/actions?limit=1&offset=1", headers=sa).json()
    assert p1["items"][0]["id"] == "s1r" and p2["items"][0]["id"] == "d1"


def test_bad_action_is_422() -> None:
    client = _build_route()
    sa = _auth(_token(client, "sa"))
    assert client.get("/v1/audit/actions?action=wizardry", headers=sa).status_code == 422


def test_bad_target_type_is_422() -> None:
    client = _build_route()
    sa = _auth(_token(client, "sa"))
    assert (
        client.get("/v1/audit/actions?target_type=galaxy", headers=sa).status_code == 422
    )


def test_bad_created_from_is_422() -> None:
    client = _build_route()
    sa = _auth(_token(client, "sa"))
    assert (
        client.get("/v1/audit/actions?created_from=not-a-date", headers=sa).status_code
        == 422
    )
