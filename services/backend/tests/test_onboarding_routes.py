"""End-to-end onboarding routes over HTTP (decisions/0025).

Real JWT + argon2 + RBAC + OnboardingService; fake school/user repos injected via a
Container subclass. Seeds a platform_admin (creates schools/admins) and a
school_admin (creates teachers) to exercise the RBAC + tenant-isolation rules.
"""

from __future__ import annotations

import pytest
from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.api.routers.staff import _tenant
from backend.domain.errors import AuthorizationError
from backend.domain.models import Role, School, User
from backend.main import create_app
from backend_fakes import FakeSchoolRepo, FakeUserRepo, SeededContainer, make_school, make_user
from fastapi.testclient import TestClient

_HASHER = Argon2PasswordHasher()


def _user(*, id: str, role: Role, school_id: str | None, password: str = "pw") -> User:
    user: User = make_user(
        id=id,
        school_id=school_id,
        email=f"{id}@x.io",
        password_hash=_HASHER.hash(password),
        role=role,
    )
    return user


def _build(*, users: list[User], schools: list[School] | None = None) -> TestClient:
    container = SeededContainer(FakeUserRepo(users), FakeSchoolRepo(schools or []))
    app = create_app()
    app.dependency_overrides[get_container_dep] = lambda: container
    return TestClient(app)


def _token(client: TestClient, who: str) -> str:
    resp = client.post("/v1/auth/login", json={"email": f"{who}@x.io", "password": "pw"})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---- platform: schools ------------------------------------------------


def test_platform_admin_creates_lists_and_fetches_schools() -> None:
    client = _build(users=[_user(id="adm", role=Role.PLATFORM_ADMIN, school_id=None)])
    token = _token(client, "adm")

    created = client.post(
        "/v1/schools", json={"name": "Springfield", "max_teachers": 3}, headers=_auth(token)
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Springfield" and body["max_teachers"] == 3
    assert body["status"] == "active"
    school_id = body["id"]

    listed = client.get("/v1/schools", headers=_auth(token))
    assert listed.status_code == 200
    assert [s["id"] for s in listed.json()["items"]] == [school_id]

    got = client.get(f"/v1/schools/{school_id}", headers=_auth(token))
    assert got.status_code == 200 and got.json()["id"] == school_id

    missing = client.get("/v1/schools/does-not-exist", headers=_auth(token))
    assert missing.status_code == 404


def test_create_school_rejects_bad_input() -> None:
    client = _build(users=[_user(id="adm", role=Role.PLATFORM_ADMIN, school_id=None)])
    token = _token(client, "adm")
    resp = client.post(
        "/v1/schools", json={"name": "X", "max_teachers": 0}, headers=_auth(token)
    )
    assert resp.status_code == 422  # max_teachers ge=1


def test_whitespace_only_name_rejected_end_to_end() -> None:
    # Passes the schema's min_length=1 but the service trims → 400 (0025).
    client = _build(users=[_user(id="adm", role=Role.PLATFORM_ADMIN, school_id=None)])
    token = _token(client, "adm")
    resp = client.post(
        "/v1/schools", json={"name": "   ", "max_teachers": 3}, headers=_auth(token)
    )
    assert resp.status_code == 400


def test_platform_admin_provisions_school_admin() -> None:
    client = _build(
        users=[_user(id="adm", role=Role.PLATFORM_ADMIN, school_id=None)],
        schools=[make_school(id="s1", max_teachers=2)],
    )
    token = _token(client, "adm")
    resp = client.post(
        "/v1/schools/s1/admins",
        json={"email": "principal@s1.io"},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # BP7c: the response is {user, temp_password} — the temp password is generated
    # server-side and returned once; the hash never leaks.
    assert body["user"]["role"] == "school_admin" and body["user"]["school_id"] == "s1"
    assert body["user"]["must_change_password"] is True
    assert "password_hash" not in body["user"]
    assert isinstance(body["temp_password"], str) and len(body["temp_password"]) >= 8


def test_school_admin_forbidden_from_platform_routes() -> None:
    client = _build(
        users=[_user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1")],
        schools=[make_school(id="s1", max_teachers=2)],
    )
    token = _token(client, "sa")
    resp = client.post(
        "/v1/schools", json={"name": "Nope", "max_teachers": 1}, headers=_auth(token)
    )
    assert resp.status_code == 403


# ---- school admin: staff ----------------------------------------------


def test_school_admin_creates_and_lists_teachers_in_own_school() -> None:
    client = _build(
        users=[_user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1")],
        schools=[make_school(id="s1", max_teachers=5)],
    )
    token = _token(client, "sa")

    created = client.post(
        "/v1/staff", json={"email": "teacher@s1.io"}, headers=_auth(token)
    )
    assert created.status_code == 201, created.text
    body = created.json()
    # Tenant isolation: the teacher lands in the admin's own school, from the token.
    assert body["user"]["role"] == "teacher" and body["user"]["school_id"] == "s1"
    assert body["user"]["must_change_password"] is True
    assert isinstance(body["temp_password"], str) and len(body["temp_password"]) >= 8

    listed = client.get("/v1/staff", headers=_auth(token))
    assert listed.status_code == 200
    rows = listed.json()["items"]
    assert [u["email"] for u in rows] == ["teacher@s1.io"]
    # The list is UserResponse[] — the one-time temp password never appears here.
    assert all("temp_password" not in u for u in rows)


def test_teacher_cap_enforced_over_http() -> None:
    client = _build(
        users=[_user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1")],
        schools=[make_school(id="s1", max_teachers=1)],
    )
    token = _token(client, "sa")
    first = client.post("/v1/staff", json={"email": "t1@s1.io"}, headers=_auth(token))
    assert first.status_code == 201
    second = client.post("/v1/staff", json={"email": "t2@s1.io"}, headers=_auth(token))
    assert second.status_code == 409  # LimitExceededError


def test_student_forbidden_from_staff_routes() -> None:
    client = _build(
        users=[_user(id="stu", role=Role.STUDENT, school_id="s1")],
        schools=[make_school(id="s1", max_teachers=5)],
    )
    token = _token(client, "stu")
    resp = client.post("/v1/staff", json={"email": "x@s1.io"}, headers=_auth(token))
    assert resp.status_code == 403


def test_staff_routes_require_auth() -> None:
    client = _build(users=[_user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1")])
    assert client.get("/v1/staff").status_code == 401


def test_tenant_helper_fails_closed_on_null_school() -> None:
    # Defense-in-depth: a school-scoped route never proceeds without a tenant.
    assert _tenant(make_user(school_id="s1")) == "s1"
    with pytest.raises(AuthorizationError):
        _tenant(make_user(school_id=None))


# ---- staff lifecycle over HTTP (BP7c) ---------------------------------


def _staff_client() -> tuple[TestClient, str]:
    client = _build(
        users=[
            _user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1"),
            _user(id="t1", role=Role.TEACHER, school_id="s1"),
        ],
        schools=[make_school(id="s1", max_teachers=5)],
    )
    return client, _token(client, "sa")


def test_admin_disables_and_reenables_a_teacher_locking_login() -> None:
    client, token = _staff_client()
    # Disable -> the teacher can no longer log in (auth rejects a disabled account).
    resp = client.patch("/v1/staff/t1", json={"status": "disabled"}, headers=_auth(token))
    assert resp.status_code == 200 and resp.json()["status"] == "disabled"
    denied = client.post("/v1/auth/login", json={"email": "t1@x.io", "password": "pw"})
    assert denied.status_code == 401
    # Re-enable -> login works again.
    resp = client.patch("/v1/staff/t1", json={"status": "active"}, headers=_auth(token))
    assert resp.status_code == 200 and resp.json()["status"] == "active"
    ok = client.post("/v1/auth/login", json={"email": "t1@x.io", "password": "pw"})
    assert ok.status_code == 200


def test_resend_invite_returns_a_new_temp_password() -> None:
    client, token = _staff_client()
    resp = client.post("/v1/staff/t1/resend-invite", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["id"] == "t1" and body["user"]["must_change_password"] is True
    assert isinstance(body["temp_password"], str) and len(body["temp_password"]) >= 8


def test_staff_lifecycle_is_tenant_and_role_scoped() -> None:
    client = _build(
        users=[
            _user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1"),
            _user(id="t2", role=Role.TEACHER, school_id="s2"),  # another school
        ],
        schools=[make_school(id="s1", max_teachers=5), make_school(id="s2")],
    )
    token = _token(client, "sa")
    # Foreign-school teacher -> 404 (no existence leak).
    assert client.patch(
        "/v1/staff/t2", json={"status": "disabled"}, headers=_auth(token)
    ).status_code == 404
    # The admin isn't a teacher -> the /staff route (role=teacher) can't touch them.
    assert client.patch(
        "/v1/staff/sa", json={"status": "disabled"}, headers=_auth(token)
    ).status_code == 404


def test_platform_admin_disables_and_reinvites_a_school_admin() -> None:
    client = _build(
        users=[
            _user(id="adm", role=Role.PLATFORM_ADMIN, school_id=None),
            _user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1"),
            # BP18b: a second active admin so disabling `sa` isn't blocked by the new
            # last-active-admin guard (which has its own dedicated tests).
            _user(id="sa2", role=Role.SCHOOL_ADMIN, school_id="s1"),
        ],
        schools=[make_school(id="s1", max_teachers=5)],
    )
    token = _token(client, "adm")
    resp = client.patch(
        "/v1/schools/s1/admins/sa", json={"status": "disabled"}, headers=_auth(token)
    )
    assert resp.status_code == 200 and resp.json()["status"] == "disabled"
    reinvite = client.post(
        "/v1/schools/s1/admins/sa/resend-invite", headers=_auth(token)
    )
    assert reinvite.status_code == 200 and len(reinvite.json()["temp_password"]) >= 8
    # Wrong school in the path -> 404 (sa belongs to s1, not s2).
    assert client.patch(
        "/v1/schools/s2/admins/sa", json={"status": "disabled"}, headers=_auth(token)
    ).status_code == 404


def test_cannot_disable_a_schools_only_admin_over_http() -> None:
    # BP18b: the last-active-admin guard surfaces as a 400 through the platform router — a
    # school can't be left with no one who can manage it.
    client = _build(
        users=[
            _user(id="adm", role=Role.PLATFORM_ADMIN, school_id=None),
            _user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1"),
        ],
        schools=[make_school(id="s1", max_teachers=5)],
    )
    token = _token(client, "adm")
    resp = client.patch(
        "/v1/schools/s1/admins/sa", json={"status": "disabled"}, headers=_auth(token)
    )
    assert resp.status_code == 400, resp.text


def test_platform_admin_edits_and_suspends_a_school() -> None:
    # BP18c: rename + cap change, then suspend + reactivate over HTTP; a partial patch
    # leaves the other fields untouched.
    client = _build(
        users=[_user(id="adm", role=Role.PLATFORM_ADMIN, school_id=None)],
        schools=[make_school(id="s1", name="Old", max_teachers=5)],
    )
    token = _token(client, "adm")
    edited = client.patch(
        "/v1/schools/s1", json={"name": "New Name", "max_teachers": 12}, headers=_auth(token)
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["name"] == "New Name" and edited.json()["max_teachers"] == 12
    suspended = client.patch(
        "/v1/schools/s1", json={"status": "suspended"}, headers=_auth(token)
    )
    assert suspended.status_code == 200 and suspended.json()["status"] == "suspended"
    assert suspended.json()["name"] == "New Name"  # partial patch kept the rename
    reactivated = client.patch(
        "/v1/schools/s1", json={"status": "active"}, headers=_auth(token)
    )
    assert reactivated.status_code == 200 and reactivated.json()["status"] == "active"


def test_update_unknown_school_is_404() -> None:
    client = _build(
        users=[_user(id="adm", role=Role.PLATFORM_ADMIN, school_id=None)],
        schools=[make_school(id="s1")],
    )
    token = _token(client, "adm")
    resp = client.patch("/v1/schools/s2", json={"name": "X"}, headers=_auth(token))
    assert resp.status_code == 404, resp.text


def test_update_school_bad_input_is_422() -> None:
    # The schema rejects a garbage status / an out-of-range cap BEFORE the service runs.
    client = _build(
        users=[_user(id="adm", role=Role.PLATFORM_ADMIN, school_id=None)],
        schools=[make_school(id="s1")],
    )
    token = _token(client, "adm")
    assert (
        client.patch(
            "/v1/schools/s1", json={"status": "deleted"}, headers=_auth(token)
        ).status_code
        == 422
    )
    assert (
        client.patch(
            "/v1/schools/s1", json={"max_teachers": 0}, headers=_auth(token)
        ).status_code
        == 422
    )
