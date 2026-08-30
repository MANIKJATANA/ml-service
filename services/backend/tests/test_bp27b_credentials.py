"""BP27 (slice 27b) — shown-once bulk credentials: student bulk-resend-invite (R4-A05) and
staff CSV bulk invite (R4-A13).

Covers the two service loops (``StudentService.bulk_resend_invite`` /
``OnboardingService.bulk_create_staff`` — best-effort loops over the tested single-writers
``resend_invite`` / ``create_teacher``) plus the routes end-to-end: the permission gates (a
student → 403 on resend; a *teacher* → 403 on ``/staff/bulk`` — admin-only; no-token → 401), the
caps (422), the never-cross-tenant resend, the shown-once secret discipline (a plaintext temp
password ONLY on a success row, never on a non-success row), and the route-ordering regression
(the bulk paths must not be shadowed by ``/{id}``).
"""

from __future__ import annotations

import pytest
from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.domain.errors import ValidationError
from backend.domain.models import (
    Role,
    School,
    SchoolStatus,
    Student,
    User,
)
from backend.main import create_app
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
    make_school,
    make_student,
    make_user,
)
from fastapi.testclient import TestClient

_S1 = "s1"
_S2 = "s2"


# ---- service builders --------------------------------------------------


def _student_svc(
    *, users: list[User], students: list[Student]
) -> tuple[StudentService, FakeStudentRepo, FakeUserRepo]:
    srepo = FakeSchoolRepo([make_school(id=_S1, max_teachers=5), make_school(id=_S2)])
    urepo = FakeUserRepo(users)
    strepo = FakeStudentRepo(students)
    grepo = FakeStudentGroupRepo()
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
        FakeMlClient(),
        FakeThumbnailer(),
        grepo,
        FakeAdminActionAuditRepo(),
        reference_photo_prefix="reference-photos",
    )
    return svc, strepo, urepo


def _onboarding_svc(
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


def _linked_pair(
    *, student_id: str, user_id: str, school_id: str, name: str
) -> tuple[User, Student]:
    """A student + its linked login (mirrors create_student's two writes) so resend touches the
    right users row and its email JOIN resolves."""
    user = make_user(
        id=user_id, school_id=school_id, email=f"{student_id}@x.io", role=Role.STUDENT
    )
    student = make_student(
        id=student_id, school_id=school_id, user_id=user_id, name=name
    )
    return user, student


# ---- bulk_resend_invite (students) -------------------------------------


async def test_bulk_resend_all_sent_distinct_passwords_and_hashes_stored() -> None:
    u1, s1 = _linked_pair(student_id="p1", user_id="u1", school_id=_S1, name="Ann")
    u2, s2 = _linked_pair(student_id="p2", user_id="u2", school_id=_S1, name="Bo")
    u3, s3 = _linked_pair(student_id="p3", user_id="u3", school_id=_S1, name="Cy")
    svc, _, urepo = _student_svc(users=[u1, u2, u3], students=[s1, s2, s3])

    results = await svc.bulk_resend_invite(
        school_id=_S1, student_ids=["p1", "p2", "p3"]
    )
    assert [r.status for r in results] == ["sent", "sent", "sent"]
    by_id = {r.student_id: r for r in results}
    # Each sent row echoes the resolved student email (a non-empty value — the fake's default).
    assert all(r.email for r in results)
    # Distinct temp passwords per account.
    passwords = [r.temp_password for r in results]
    assert all(p for p in passwords)
    assert len(set(passwords)) == 3  # random per account
    # The NEW temp password's hash is persisted for each (FakeHasher: 'hash:'+pw).
    assert (await urepo.get("u1")).password_hash == f"hash:{by_id['p1'].temp_password}"
    assert (await urepo.get("u2")).password_hash == f"hash:{by_id['p2'].temp_password}"
    # ...and each must now change their password on next login.
    assert (await urepo.get("u3")).must_change_password is True


async def test_bulk_resend_isolates_a_foreign_id_with_empty_email_and_no_password() -> None:
    u1, s1 = _linked_pair(student_id="p1", user_id="u1", school_id=_S1, name="Ann")
    uf, sf = _linked_pair(student_id="pf", user_id="uf", school_id=_S2, name="Foreign")
    svc, strepo, urepo = _student_svc(users=[u1, uf], students=[s1, sf])
    before = (await urepo.get("uf")).password_hash

    results = await svc.bulk_resend_invite(school_id=_S1, student_ids=["pf", "p1"])
    by_id = {r.student_id: r for r in results}
    assert by_id["pf"].status == "error"
    # SF-1: the failure path never reads the (unresolved) student's email — it's "".
    assert by_id["pf"].email == ""
    assert by_id["pf"].temp_password is None
    # The batch still resent p1.
    assert by_id["p1"].status == "sent" and by_id["p1"].temp_password
    # The foreign student's login is untouched (no password write).
    assert (await urepo.get("uf")).password_hash == before


async def test_bulk_resend_every_non_sent_row_has_no_password() -> None:
    # Two foreign/unknown ids + one real: every non-sent row must carry temp_password=None.
    u1, s1 = _linked_pair(student_id="p1", user_id="u1", school_id=_S1, name="Ann")
    svc, _, _ = _student_svc(users=[u1], students=[s1])
    results = await svc.bulk_resend_invite(
        school_id=_S1, student_ids=["nope", "p1", "also-nope"]
    )
    for r in results:
        if r.status != "sent":
            assert r.temp_password is None
        else:
            assert r.temp_password  # only the sent row carries the plaintext


# ---- bulk_create_staff (teachers) --------------------------------------


async def test_bulk_create_staff_all_created_distinct_passwords() -> None:
    svc, _, urepo = _onboarding_svc(schools=[make_school(id="s1", max_teachers=10)])
    results = await svc.bulk_create_staff(
        school_id="s1", emails=["a@x.io", "b@x.io", "c@x.io"]
    )
    assert [r.status for r in results] == ["created", "created", "created"]
    passwords = [r.temp_password for r in results]
    assert all(p for p in passwords)
    assert len(set(passwords)) == 3  # random per account
    # All three teachers now exist in the school.
    assert await urepo.count_by_school_and_role("s1", Role.TEACHER) == 3


async def test_bulk_create_staff_duplicate_is_bare_no_message_no_password() -> None:
    existing = make_user(id="t1", school_id="s1", email="dup@x.io", role=Role.TEACHER)
    svc, _, _ = _onboarding_svc(
        schools=[make_school(id="s1", max_teachers=10)], users=[existing]
    )
    results = await svc.bulk_create_staff(school_id="s1", emails=["dup@x.io", "new@x.io"])
    by_email = {r.email: r for r in results}
    # SF-2: a duplicate is a bare verdict — no error message, no temp_password (the conflict
    # message must never leak).
    assert by_email["dup@x.io"].status == "duplicate"
    assert by_email["dup@x.io"].error is None
    assert by_email["dup@x.io"].temp_password is None
    # The batch still created the new one.
    assert by_email["new@x.io"].status == "created" and by_email["new@x.io"].temp_password


async def test_bulk_create_staff_cross_school_duplicate_is_duplicate() -> None:
    # uq_users_email is global — an email already used in ANOTHER school is a duplicate here.
    other = make_user(id="t2", school_id="s2", email="shared@x.io", role=Role.TEACHER)
    svc, _, _ = _onboarding_svc(
        schools=[
            make_school(id="s1", max_teachers=10),
            make_school(id="s2", max_teachers=10),
        ],
        users=[other],
    )
    results = await svc.bulk_create_staff(school_id="s1", emails=["shared@x.io"])
    assert results[0].status == "duplicate"
    assert results[0].temp_password is None


async def test_bulk_create_staff_invalid_email_carries_a_message_no_password() -> None:
    svc, _, _ = _onboarding_svc(schools=[make_school(id="s1", max_teachers=10)])
    results = await svc.bulk_create_staff(
        school_id="s1", emails=["not-an-email", "ok@x.io"]
    )
    by_email = {r.email: r for r in results}
    # An invalid row carries the message + no password (and the ORIGINAL email string is echoed).
    assert by_email["not-an-email"].status == "invalid"
    assert by_email["not-an-email"].error is not None
    assert by_email["not-an-email"].temp_password is None
    assert by_email["ok@x.io"].status == "created"


async def test_bulk_create_staff_cap_partial_stops_at_the_limit() -> None:
    # SF-6 precondition: the fake's count reflects created rows.
    existing = make_user(id="t0", school_id="s1", email="t0@x.io", role=Role.TEACHER)
    svc, _, urepo = _onboarding_svc(
        schools=[make_school(id="s1", max_teachers=2)], users=[existing]
    )
    assert await urepo.count_by_school_and_role("s1", Role.TEACHER) == 1
    # max_teachers=2 + 1 existing → exactly 1 more can be created; the other 2 hit the cap.
    results = await svc.bulk_create_staff(
        school_id="s1", emails=["a@x.io", "b@x.io", "c@x.io"]
    )
    statuses = [r.status for r in results]
    assert statuses.count("created") == 1
    assert statuses.count("limit_reached") == 2
    # limit_reached rows carry no password.
    assert all(r.temp_password is None for r in results if r.status == "limit_reached")
    assert await urepo.count_by_school_and_role("s1", Role.TEACHER) == 2


async def test_bulk_create_staff_suspended_school_raises_before_any_write() -> None:
    svc, _, urepo = _onboarding_svc(
        schools=[make_school(id="s1", max_teachers=10, status=SchoolStatus.SUSPENDED)]
    )
    with pytest.raises(ValidationError):
        await svc.bulk_create_staff(school_id="s1", emails=["a@x.io", "b@x.io"])
    # No teacher was created (the pre-check aborts the whole batch).
    assert await urepo.count_by_school_and_role("s1", Role.TEACHER) == 0


async def test_bulk_create_staff_every_non_created_row_has_no_password() -> None:
    existing = make_user(id="t1", school_id="s1", email="dup@x.io", role=Role.TEACHER)
    svc, _, _ = _onboarding_svc(
        schools=[make_school(id="s1", max_teachers=10)], users=[existing]
    )
    results = await svc.bulk_create_staff(
        school_id="s1", emails=["dup@x.io", "bad email", "fresh@x.io"]
    )
    for r in results:
        if r.status != "created":
            assert r.temp_password is None
        else:
            assert r.temp_password  # only created rows carry the plaintext


# ---- routes ------------------------------------------------------------

_HASHER = Argon2PasswordHasher()


def _user(*, id: str, role: Role, school_id: str | None, email: str) -> User:
    user: User = make_user(
        id=id, school_id=school_id, email=email, password_hash=_HASHER.hash("pw"), role=role
    )
    return user


def _student_client() -> tuple[TestClient, SeededContainer]:
    """s1: an admin + a teacher (lacks staff:manage) + three students (each a linked login) + a
    student login of their own (lacks student:manage). s2: an admin + a student, so a route test can
    prove a foreign id can never be resent cross-tenant through the full token→tenant_of stack."""
    users = [
        _user(id="sa", role=Role.SCHOOL_ADMIN, school_id=_S1, email="sa@x.io"),
        _user(id="tt", role=Role.TEACHER, school_id=_S1, email="tt@x.io"),
        _user(id="u1", role=Role.STUDENT, school_id=_S1, email="p1@x.io"),
        _user(id="u2", role=Role.STUDENT, school_id=_S1, email="p2@x.io"),
        _user(id="u3", role=Role.STUDENT, school_id=_S1, email="p3@x.io"),
        _user(id="sa2", role=Role.SCHOOL_ADMIN, school_id=_S2, email="sa2@x.io"),
        _user(id="uf", role=Role.STUDENT, school_id=_S2, email="pf@x.io"),
    ]
    students = FakeStudentRepo(
        [
            make_student(id="p1", school_id=_S1, user_id="u1", name="Ann"),
            make_student(id="p2", school_id=_S1, user_id="u2", name="Bo"),
            make_student(id="p3", school_id=_S1, user_id="u3", name="Cy"),
            make_student(id="pf", school_id=_S2, user_id="uf", name="Foreign"),
        ]
    )
    container = SeededContainer(
        FakeUserRepo(users),
        FakeSchoolRepo([make_school(id=_S1), make_school(id=_S2)]),
        students=students,
    )
    app = create_app()
    app.dependency_overrides[get_container_dep] = lambda: container
    return TestClient(app), container


def _staff_client(*, max_teachers: int = 10) -> tuple[TestClient, SeededContainer]:
    """s1: an admin (staff:manage) + a teacher (no staff:manage) so the 403 case has a token that
    is authenticated but not an admin."""
    users = [
        _user(id="sa", role=Role.SCHOOL_ADMIN, school_id=_S1, email="sa@x.io"),
        _user(id="tt", role=Role.TEACHER, school_id=_S1, email="tt@x.io"),
    ]
    container = SeededContainer(
        FakeUserRepo(users),
        FakeSchoolRepo([make_school(id=_S1, max_teachers=max_teachers)]),
    )
    app = create_app()
    app.dependency_overrides[get_container_dep] = lambda: container
    return TestClient(app), container


def _token(client: TestClient, who: str) -> str:
    resp = client.post("/v1/auth/login", json={"email": f"{who}@x.io", "password": "pw"})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---- student bulk-resend routes ----------------------------------------


def test_bulk_resend_route_returns_passwords_only_on_sent_rows() -> None:
    client, _ = _student_client()
    sa = _auth(_token(client, "sa"))
    resp = client.post(
        "/v1/students/bulk-resend-invite",
        headers=sa,
        json={"student_ids": ["p1", "p2", "nope"]},
    )
    assert resp.status_code == 200, resp.text
    by_id = {r["student_id"]: r for r in resp.json()["results"]}
    assert by_id["p1"]["status"] == "sent" and by_id["p1"]["temp_password"]
    assert by_id["p2"]["status"] == "sent" and by_id["p2"]["temp_password"]
    # A non-sent (unknown) row: error, no password.
    assert by_id["nope"]["status"] == "error"
    assert by_id["nope"]["temp_password"] is None
    assert by_id["nope"]["email"] == ""


def test_bulk_resend_route_never_cross_tenant() -> None:
    # End-to-end (token → tenant_of → service): the s1 admin posts a REAL s2 student id. It's
    # `error` (no password), and the foreign account's password is untouched — it can STILL log in
    # with its original password afterwards (inspected via an s2 login).
    client, _ = _student_client()
    sa = _auth(_token(client, "sa"))  # s1 admin
    resp = client.post(
        "/v1/students/bulk-resend-invite",
        headers=sa,
        json={"student_ids": ["pf", "p1"]},
    )
    assert resp.status_code == 200, resp.text
    by_id = {r["student_id"]: r for r in resp.json()["results"]}
    assert by_id["pf"]["status"] == "error" and by_id["pf"]["temp_password"] is None
    assert by_id["p1"]["status"] == "sent"
    # The foreign student's password was NOT reset — its original still works.
    assert client.post(
        "/v1/auth/login", json={"email": "pf@x.io", "password": "pw"}
    ).status_code == 200


def test_bulk_resend_route_requires_student_manage_and_auth() -> None:
    client, _ = _student_client()
    body = {"student_ids": ["p1"]}
    # A student token lacks student:manage → 403.
    stu = _auth(_token(client, "p1"))
    assert client.post(
        "/v1/students/bulk-resend-invite", headers=stu, json=body
    ).status_code == 403
    # No token → 401.
    assert client.post("/v1/students/bulk-resend-invite", json=body).status_code == 401


def test_bulk_resend_route_validates_the_body() -> None:
    client, _ = _student_client()
    sa = _auth(_token(client, "sa"))
    # Empty → 422 (schema min_length=1).
    assert client.post(
        "/v1/students/bulk-resend-invite", headers=sa, json={"student_ids": []}
    ).status_code == 422
    # Over the cap (_MAX_BULK_IDS = 1000) → 422.
    ids = [f"x{i}" for i in range(1001)]
    assert client.post(
        "/v1/students/bulk-resend-invite", headers=sa, json={"student_ids": ids}
    ).status_code == 422


def test_bulk_resend_route_is_not_shadowed_by_the_wildcard() -> None:
    # Regression guard: POST /v1/students/bulk-resend-invite must NOT be swallowed by a
    # /{student_id} route. A 200 (not a 404/405) proves the literal path is matched.
    client, _ = _student_client()
    sa = _auth(_token(client, "sa"))
    resp = client.post(
        "/v1/students/bulk-resend-invite", headers=sa, json={"student_ids": ["p1"]}
    )
    assert resp.status_code == 200, resp.text


# ---- staff bulk-invite routes ------------------------------------------


def test_staff_bulk_route_creates_and_returns_passwords_only_on_created() -> None:
    client, _ = _staff_client()
    sa = _auth(_token(client, "sa"))
    # One good + one malformed + one duplicate (of the first, in batch) → created/invalid/duplicate.
    resp = client.post(
        "/v1/staff/bulk",
        headers=sa,
        json={"emails": ["a@x.io", "bad email", "a@x.io"]},
    )
    assert resp.status_code == 201, resp.text
    rows = resp.json()["results"]
    assert [r["status"] for r in rows] == ["created", "invalid", "duplicate"]
    # temp_password ONLY on the created row.
    assert rows[0]["temp_password"]
    assert rows[1]["temp_password"] is None
    assert rows[2]["temp_password"] is None
    # The duplicate carries no error message (bare verdict).
    assert rows[2]["error"] is None


def test_staff_bulk_route_forbidden_for_a_teacher() -> None:
    # The NON-OBVIOUS authZ case: a teacher is authenticated but lacks staff:manage (admin-only),
    # so /staff/bulk is 403 for them (not 401).
    client, _ = _staff_client()
    tt = _auth(_token(client, "tt"))
    assert client.post(
        "/v1/staff/bulk", headers=tt, json={"emails": ["a@x.io"]}
    ).status_code == 403


def test_staff_bulk_route_forbidden_for_a_student_and_requires_auth() -> None:
    client, _ = _student_client()
    # A student token → 403.
    stu = _auth(_token(client, "p1"))
    assert client.post(
        "/v1/staff/bulk", headers=stu, json={"emails": ["a@x.io"]}
    ).status_code == 403
    # No token → 401.
    assert client.post("/v1/staff/bulk", json={"emails": ["a@x.io"]}).status_code == 401


def test_staff_bulk_route_validates_the_body() -> None:
    client, _ = _staff_client()
    sa = _auth(_token(client, "sa"))
    # Empty → 422 (schema min_length=1).
    assert client.post(
        "/v1/staff/bulk", headers=sa, json={"emails": []}
    ).status_code == 422
    # Over the cap (_MAX_BULK_STAFF = 100) → 422.
    emails = [f"t{i}@x.io" for i in range(101)]
    assert client.post(
        "/v1/staff/bulk", headers=sa, json={"emails": emails}
    ).status_code == 422


def test_staff_bulk_route_cap_partial_over_http() -> None:
    # The client already seeds one teacher (`tt`); with max_teachers=2 there's room for exactly one
    # more → the first email is created, the second reports limit_reached (best-effort, 201 with a
    # mixed body — NOT a 409 that aborts).
    client, _ = _staff_client(max_teachers=2)
    sa = _auth(_token(client, "sa"))
    resp = client.post(
        "/v1/staff/bulk", headers=sa, json={"emails": ["a@x.io", "b@x.io"]}
    )
    assert resp.status_code == 201, resp.text
    rows = resp.json()["results"]
    assert rows[0]["status"] == "created" and rows[0]["temp_password"]
    assert rows[1]["status"] == "limit_reached" and rows[1]["temp_password"] is None


def test_staff_bulk_route_is_not_shadowed_by_the_wildcard() -> None:
    # Regression guard: POST /v1/staff/bulk must not be swallowed by /{user_id} (there is a
    # PATCH /{user_id} + POST /{user_id}/resend-invite). A 201 proves the literal path is matched.
    client, _ = _staff_client()
    sa = _auth(_token(client, "sa"))
    resp = client.post("/v1/staff/bulk", headers=sa, json={"emails": ["solo@x.io"]})
    assert resp.status_code == 201, resp.text
