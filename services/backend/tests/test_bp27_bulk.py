"""BP27 (slice 27a) — bulk disable/enable + bulk delete of students, and select-all-matching.

The service-level bulk loops (``StudentService.bulk_set_status`` / ``bulk_delete_students`` —
pure best-effort loops over the tested single-writers ``set_status`` / ``delete_student``) and the
id-scan (``ListingService.list_student_ids`` — the whole matching set so a bulk action spans
pages), then the routes end-to-end: the ``student:manage`` gate, the caps (422), the mixed-id
best-effort outcome, and the ``/ids`` regression guard (it must not be shadowed by the wildcard).
"""

from __future__ import annotations

import pytest
from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.domain.errors import UpstreamError
from backend.domain.models import (
    EnrollmentOutcome,
    EnrollmentStatus,
    Role,
    Student,
    StudentGroup,
    User,
    UserStatus,
)
from backend.domain.ports import MlEnrollmentClient
from backend.main import create_app
from backend.services.class_service import ClassService
from backend.services.listing_service import ListingService
from backend.services.student_service import StudentService
from backend_fakes import (
    FakeEventRepo,
    FakeHasher,
    FakeMediaRepo,
    FakeMlClient,
    FakeMlResultsReader,
    FakeObjectStore,
    FakeSchoolRepo,
    FakeStudentGroupRepo,
    FakeStudentRepo,
    FakeThumbnailer,
    FakeUserRepo,
    SeededContainer,
    make_school,
    make_student,
    make_student_group,
    make_user,
)
from fastapi.testclient import TestClient

_S1 = "s1"
_S2 = "s2"


# ---- service builders --------------------------------------------------


class SpyMlClient:
    """MlEnrollmentClient double that raises on ``delete`` for one specific student id (BP27:
    prove a single row's ML failure is isolated — the other rows still delete). Records the
    deletes that DID succeed. Enroll is never reached by these delete-path tests."""

    def __init__(self, *, raise_delete_for: str) -> None:
        self._raise_delete_for = raise_delete_for
        self.delete_calls: list[tuple[str, str]] = []

    async def enroll(
        self, *, school_id: str, student_id: str, photo_uris: list[str]
    ) -> EnrollmentOutcome:  # pragma: no cover - not exercised by delete tests
        raise NotImplementedError

    async def delete(self, *, school_id: str, student_id: str) -> None:
        if student_id == self._raise_delete_for:
            raise UpstreamError(f"ML delete failed for {student_id}")
        self.delete_calls.append((school_id, student_id))


def _student_svc(
    *,
    users: list[User],
    students: list[Student],
    ml_client: MlEnrollmentClient | None = None,
) -> tuple[StudentService, FakeStudentRepo, FakeUserRepo, MlEnrollmentClient]:
    srepo = FakeSchoolRepo([make_school(id=_S1, max_teachers=5), make_school(id=_S2)])
    urepo = FakeUserRepo(users)
    strepo = FakeStudentRepo(students)
    grepo = FakeStudentGroupRepo()
    urepo.link_cascade(strepo.remove_by_user)  # mirror the users.user_id ON DELETE CASCADE
    strepo.link_users(urepo.email_of)
    strepo.link_user_status(urepo.status_of)  # BP18d: status on the read model (disable)
    strepo.link_groups(grepo.name_of)
    ml = ml_client or FakeMlClient()
    svc = StudentService(
        strepo,
        urepo,
        srepo,
        FakeHasher(),
        FakeObjectStore(),
        ml,
        FakeThumbnailer(),
        grepo,
        reference_photo_prefix="reference-photos",
    )
    return svc, strepo, urepo, ml


def _listing_svc(
    *, students: list[Student]
) -> tuple[ListingService, FakeStudentRepo]:
    strepo = FakeStudentRepo(students)
    svc = ListingService(
        FakeSchoolRepo(),
        FakeUserRepo(),
        strepo,
        FakeEventRepo(),
        FakeMediaRepo(),
        FakeMlResultsReader(),
    )
    return svc, strepo


def _class_svc(
    *, students: list[Student], groups: list[StudentGroup]
) -> tuple[ClassService, FakeStudentRepo, FakeStudentGroupRepo]:
    """A ClassService wired to the same fakes as the container (BP27c remove-from-class): the
    student read carries its class name (LEFT JOIN) and deleting a class un-assigns its students."""
    strepo = FakeStudentRepo(students)
    grepo = FakeStudentGroupRepo(groups)
    strepo.link_groups(grepo.name_of)
    grepo.link_students(strepo.group_counts, on_delete=strepo.unassign_group)
    return ClassService(grepo, strepo), strepo, grepo


def _linked_pair(
    *, student_id: str, user_id: str, school_id: str, name: str
) -> tuple[User, Student]:
    """A student + its linked login (mirrors create_student's two writes) so delete's cascade
    and set_status's users JOIN behave like the real thing."""
    user = make_user(
        id=user_id, school_id=school_id, email=f"{student_id}@x.io", role=Role.STUDENT
    )
    student = make_student(
        id=student_id, school_id=school_id, user_id=user_id, name=name
    )
    return user, student


# ---- bulk_set_status ---------------------------------------------------


async def test_bulk_set_status_flips_all_own_ids() -> None:
    u1, s1 = _linked_pair(student_id="p1", user_id="u1", school_id=_S1, name="Ann")
    u2, s2 = _linked_pair(student_id="p2", user_id="u2", school_id=_S1, name="Bo")
    u3, s3 = _linked_pair(student_id="p3", user_id="u3", school_id=_S1, name="Cy")
    svc, strepo, _ = _student_svc(users=[u1, u2, u3], students=[s1, s2, s3])[:3]

    results = await svc.bulk_set_status(
        school_id=_S1, student_ids=["p1", "p2"], status=UserStatus.DISABLED
    )
    assert [r.status for r in results] == ["ok", "ok"]
    # The two selected are disabled; the non-selected one stays active.
    assert (await strepo.get(_S1, "p1")).status is UserStatus.DISABLED
    assert (await strepo.get(_S1, "p2")).status is UserStatus.DISABLED
    assert (await strepo.get(_S1, "p3")).status is UserStatus.ACTIVE


async def test_bulk_set_status_isolates_a_foreign_id_and_continues() -> None:
    u1, s1 = _linked_pair(student_id="p1", user_id="u1", school_id=_S1, name="Ann")
    uf, sf = _linked_pair(student_id="pf", user_id="uf", school_id=_S2, name="Foreign")
    svc, strepo, _ = _student_svc(users=[u1, uf], students=[s1, sf])[:3]

    # "pf" belongs to s2 — set_status 404s it (error), but "p1" still flips (batch never aborts).
    results = await svc.bulk_set_status(
        school_id=_S1, student_ids=["pf", "p1"], status=UserStatus.DISABLED
    )
    by_id = {r.student_id: r.status for r in results}
    assert by_id == {"pf": "error", "p1": "ok"}
    assert (await strepo.get(_S1, "p1")).status is UserStatus.DISABLED
    # The foreign student is untouched (still active in its own school).
    assert (await strepo.get(_S2, "pf")).status is UserStatus.ACTIVE


async def test_bulk_set_status_enable_is_the_inverse() -> None:
    u1, s1 = _linked_pair(student_id="p1", user_id="u1", school_id=_S1, name="Ann")
    svc, strepo, urepo = _student_svc(users=[u1], students=[s1])[:3]
    urepo.mutate("u1", status=UserStatus.DISABLED)  # start disabled

    results = await svc.bulk_set_status(
        school_id=_S1, student_ids=["p1"], status=UserStatus.ACTIVE
    )
    assert [r.status for r in results] == ["ok"]
    assert (await strepo.get(_S1, "p1")).status is UserStatus.ACTIVE


# ---- bulk_delete_students ----------------------------------------------


async def test_bulk_delete_removes_all_and_calls_ml() -> None:
    u1, s1 = _linked_pair(student_id="p1", user_id="u1", school_id=_S1, name="Ann")
    u2, s2 = _linked_pair(student_id="p2", user_id="u2", school_id=_S1, name="Bo")
    ml = FakeMlClient()  # a handle whose recorded delete_calls we assert on
    svc, strepo, _, _ = _student_svc(users=[u1, u2], students=[s1, s2], ml_client=ml)

    results = await svc.bulk_delete_students(school_id=_S1, student_ids=["p1", "p2"])
    assert [r.status for r in results] == ["ok", "ok"]
    # Both gone; both had their ML footprint removed.
    assert await strepo.get(_S1, "p1") is None
    assert await strepo.get(_S1, "p2") is None
    assert set(ml.delete_calls) == {(_S1, "p1"), (_S1, "p2")}


async def test_bulk_delete_isolates_one_ml_failure_others_still_deleted() -> None:
    u1, s1 = _linked_pair(student_id="p1", user_id="u1", school_id=_S1, name="Ann")
    u2, s2 = _linked_pair(student_id="p2", user_id="u2", school_id=_S1, name="Bo")
    u3, s3 = _linked_pair(student_id="p3", user_id="u3", school_id=_S1, name="Cy")
    ml = SpyMlClient(raise_delete_for="p2")
    svc, strepo, _, _ = _student_svc(
        users=[u1, u2, u3], students=[s1, s2, s3], ml_client=ml
    )

    results = await svc.bulk_delete_students(
        school_id=_S1, student_ids=["p1", "p2", "p3"]
    )
    by_id = {r.student_id: r.status for r in results}
    assert by_id == {"p1": "ok", "p2": "error", "p3": "ok"}
    # p2's ML delete raised (502) BEFORE the login delete, so p2 survives; the others are gone —
    # the batch never aborted.
    assert await strepo.get(_S1, "p1") is None
    assert await strepo.get(_S1, "p2") is not None
    assert await strepo.get(_S1, "p3") is None


async def test_bulk_delete_isolates_a_foreign_id() -> None:
    u1, s1 = _linked_pair(student_id="p1", user_id="u1", school_id=_S1, name="Ann")
    uf, sf = _linked_pair(student_id="pf", user_id="uf", school_id=_S2, name="Foreign")
    svc, strepo, _, _ = _student_svc(users=[u1, uf], students=[s1, sf])

    results = await svc.bulk_delete_students(school_id=_S1, student_ids=["pf", "p1"])
    by_id = {r.student_id: r.status for r in results}
    assert by_id == {"pf": "error", "p1": "ok"}
    assert await strepo.get(_S1, "p1") is None
    # The foreign student is never touched.
    assert await strepo.get(_S2, "pf") is not None


async def test_bulk_delete_retry_self_heals_via_idempotent_ml_delete() -> None:
    # A row whose delete previously errored (e.g. login-delete blipped after ML delete succeeded)
    # can be re-run: the ML DELETE is idempotent (deleting an absent student is a no-op), so a
    # second delete of the same id completes cleanly rather than 500ing.
    u1, s1 = _linked_pair(student_id="p1", user_id="u1", school_id=_S1, name="Ann")
    ml = FakeMlClient()  # a handle so we can re-invoke its idempotent delete directly
    svc, strepo, _, _ = _student_svc(users=[u1], students=[s1], ml_client=ml)

    first = await svc.bulk_delete_students(school_id=_S1, student_ids=["p1"])
    assert [r.status for r in first] == ["ok"]
    assert await strepo.get(_S1, "p1") is None
    # Retrying the (now-gone) id: get_student 404s → error, but it does NOT raise/abort.
    second = await svc.bulk_delete_students(school_id=_S1, student_ids=["p1"])
    assert [r.status for r in second] == ["error"]  # already gone
    # And a direct idempotent ML delete of an absent id is a clean no-op (the self-heal contract).
    await ml.delete(school_id=_S1, student_id="p1")  # does not raise


# ---- list_student_ids (select-all-matching) ----------------------------


async def test_list_student_ids_matches_the_page_list_id_set() -> None:
    students = [
        make_student(id="p1", school_id=_S1, enrollment_status=EnrollmentStatus.ENROLLED),
        make_student(id="p2", school_id=_S1, enrollment_status=EnrollmentStatus.FAILED),
        make_student(id="p3", school_id=_S1, enrollment_status=EnrollmentStatus.ENROLLED),
        make_student(id="pf", school_id=_S2, enrollment_status=EnrollmentStatus.ENROLLED),
    ]
    svc, _ = _listing_svc(students=students)

    # No filter: every in-school id, tenant-scoped (the foreign one excluded), total == len.
    scan = await svc.list_student_ids(school_id=_S1)
    assert set(scan.ids) == {"p1", "p2", "p3"}
    assert scan.total == 3 == len(scan.ids)

    # Same id set the paged list would show for a status filter.
    page = await svc.list_students_page(
        school_id=_S1, limit=50, offset=0, status=EnrollmentStatus.ENROLLED
    )
    filtered = await svc.list_student_ids(
        school_id=_S1, status=EnrollmentStatus.ENROLLED
    )
    assert set(filtered.ids) == {s.student.id for s in page.items} == {"p1", "p3"}


async def test_list_student_ids_honors_the_mine_scope() -> None:
    students = [
        make_student(id="p1", school_id=_S1, student_group_id="c1"),
        make_student(id="p2", school_id=_S1, student_group_id="c2"),
        make_student(id="p3", school_id=_S1, student_group_id=None),  # un-classed
    ]
    svc, _ = _listing_svc(students=students)
    # A teacher focused on class c1 sees only c1's students (un-classed is no teacher's).
    scan = await svc.list_student_ids(school_id=_S1, scope_group_ids=["c1"])
    assert set(scan.ids) == {"p1"}
    assert scan.total == 1


# ---- remove_students_bulk (BP27c) --------------------------------------


async def test_remove_students_bulk_clears_selected_only() -> None:
    # p1/p2/p3 all in class c1; removing p1+p2 clears their pointer, p3 keeps its class.
    grp = make_student_group(id="c1", school_id=_S1, name="3B")
    students = [
        make_student(id="p1", school_id=_S1, student_group_id="c1", student_group_name="3B"),
        make_student(id="p2", school_id=_S1, student_group_id="c1", student_group_name="3B"),
        make_student(id="p3", school_id=_S1, student_group_id="c1", student_group_name="3B"),
    ]
    svc, strepo, _ = _class_svc(students=students, groups=[grp])

    results = await svc.remove_students_bulk(school_id=_S1, student_ids=["p1", "p2"])
    assert [r.status for r in results] == ["ok", "ok"]
    assert (await strepo.get(_S1, "p1")).student_group_id is None
    assert (await strepo.get(_S1, "p2")).student_group_id is None
    # The non-selected same-class student keeps its group.
    assert (await strepo.get(_S1, "p3")).student_group_id == "c1"


async def test_remove_students_bulk_isolates_a_foreign_id_and_continues() -> None:
    # "s2" is a student in the OTHER school (in its own class); the s1 caller can't touch it —
    # set_student_group 404s it (error), but p1 still clears (the batch never aborts).
    grp1 = make_student_group(id="c1", school_id=_S1, name="3B")
    grp2 = make_student_group(id="c2", school_id=_S2, name="4A")
    students = [
        make_student(id="p1", school_id=_S1, student_group_id="c1", student_group_name="3B"),
        make_student(id="s2", school_id=_S2, student_group_id="c2", student_group_name="4A"),
    ]
    svc, strepo, _ = _class_svc(students=students, groups=[grp1, grp2])

    results = await svc.remove_students_bulk(school_id=_S1, student_ids=["s2", "p1"])
    by_id = {r.student_id: r.status for r in results}
    assert by_id == {"s2": "error", "p1": "ok"}
    assert (await strepo.get(_S1, "p1")).student_group_id is None
    # The foreign student is untouched — still in its class in s2.
    assert (await strepo.get(_S2, "s2")).student_group_id == "c2"


async def test_remove_students_bulk_unknown_id_is_error() -> None:
    grp = make_student_group(id="c1", school_id=_S1, name="3B")
    students = [
        make_student(id="p1", school_id=_S1, student_group_id="c1", student_group_name="3B"),
    ]
    svc, strepo, _ = _class_svc(students=students, groups=[grp])

    results = await svc.remove_students_bulk(school_id=_S1, student_ids=["p1", "nope"])
    by_id = {r.student_id: r.status for r in results}
    assert by_id == {"p1": "ok", "nope": "error"}
    assert (await strepo.get(_S1, "p1")).student_group_id is None


# ---- routes ------------------------------------------------------------

_HASHER = Argon2PasswordHasher()


def _user(*, id: str, role: Role, school_id: str | None, email: str) -> User:
    user: User = make_user(
        id=id, school_id=school_id, email=email, password_hash=_HASHER.hash("pw"), role=role
    )
    return user


def _build() -> tuple[TestClient, SeededContainer]:
    """School s1: an admin + three students (p1/p2/p3, each with a linked login) + a student
    login of their own so the 403 path has a token lacking student:manage. A SECOND school s2
    (admin sa2 + student pf) lets a route test prove a foreign id can never be written cross-tenant
    through the full token->tenant_of->service stack."""
    users = [
        _user(id="sa", role=Role.SCHOOL_ADMIN, school_id=_S1, email="sa@x.io"),
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


def _token(client: TestClient, who: str) -> str:
    resp = client.post("/v1/auth/login", json={"email": f"{who}@x.io", "password": "pw"})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_bulk_status_round_trip_disables_only_the_selected() -> None:
    client, _ = _build()
    sa = _auth(_token(client, "sa"))
    resp = client.post(
        "/v1/students/bulk-status",
        headers=sa,
        json={"student_ids": ["p1", "p2"], "status": "disabled"},
    )
    assert resp.status_code == 200, resp.text
    assert {r["student_id"]: r["status"] for r in resp.json()["results"]} == {
        "p1": "ok",
        "p2": "ok",
    }
    # p1/p2 read disabled; p3 (not selected) stays active.
    assert client.get("/v1/students/p1", headers=sa).json()["status"] == "disabled"
    assert client.get("/v1/students/p2", headers=sa).json()["status"] == "disabled"
    assert client.get("/v1/students/p3", headers=sa).json()["status"] == "active"


def test_bulk_delete_then_the_deleted_id_is_404() -> None:
    client, _ = _build()
    sa = _auth(_token(client, "sa"))
    resp = client.post(
        "/v1/students/bulk-delete", headers=sa, json={"student_ids": ["p1"]}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["results"] == [{"student_id": "p1", "status": "ok"}]
    assert client.get("/v1/students/p1", headers=sa).status_code == 404
    assert client.get("/v1/students/p2", headers=sa).status_code == 200  # untouched


def test_bulk_status_mixed_ids_are_best_effort() -> None:
    client, _ = _build()
    sa = _auth(_token(client, "sa"))
    resp = client.post(
        "/v1/students/bulk-status",
        headers=sa,
        json={"student_ids": ["p1", "nope"], "status": "disabled"},
    )
    assert resp.status_code == 200, resp.text
    assert {r["student_id"]: r["status"] for r in resp.json()["results"]} == {
        "p1": "ok",
        "nope": "error",
    }


def test_bulk_routes_never_cross_tenant_write() -> None:
    # End-to-end (token -> tenant_of -> service): the s1 admin posts a REAL foreign-school (s2)
    # student id. It comes back `error` (best-effort, the batch still flips p1), and the foreign
    # student is never disabled or deleted — still active + present in its OWN school (inspected
    # with an s2 admin token).
    client, _ = _build()
    sa = _auth(_token(client, "sa"))  # s1 admin
    sa2 = _auth(_token(client, "sa2"))  # s2 admin — to inspect pf in its own tenant
    resp = client.post(
        "/v1/students/bulk-status",
        headers=sa,
        json={"student_ids": ["pf", "p1"], "status": "disabled"},
    )
    assert resp.status_code == 200, resp.text
    assert {r["student_id"]: r["status"] for r in resp.json()["results"]} == {
        "pf": "error",
        "p1": "ok",
    }
    # The foreign student is untouched — still active in its own school (s2).
    assert client.get("/v1/students/pf", headers=sa2).json()["status"] == "active"
    # A foreign id can't be erased through bulk-delete either — it survives in s2.
    resp2 = client.post(
        "/v1/students/bulk-delete", headers=sa, json={"student_ids": ["pf"]}
    )
    assert resp2.json()["results"] == [{"student_id": "pf", "status": "error"}]
    assert client.get("/v1/students/pf", headers=sa2).status_code == 200


def test_list_student_ids_route_returns_the_id_envelope() -> None:
    # Regression guard: GET /v1/students/ids must NOT be swallowed by GET /v1/students/{id}
    # (which would 404 treating "ids" as a student_id). Registered before the wildcard.
    client, _ = _build()
    sa = _auth(_token(client, "sa"))
    resp = client.get("/v1/students/ids", headers=sa)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body["ids"]) == {"p1", "p2", "p3"}
    assert body["total"] == 3


def test_list_student_ids_route_honors_the_status_filter() -> None:
    client, _ = _build()
    sa = _auth(_token(client, "sa"))
    # Disable p1 via bulk, then a status filter still returns ids (the id set the list shows).
    client.post(
        "/v1/students/bulk-status",
        headers=sa,
        json={"student_ids": ["p1"], "status": "disabled"},
    )
    resp = client.get("/v1/students/ids?status=pending", headers=sa)
    assert resp.status_code == 200, resp.text
    # All three are enrollment=pending (a disabled login is a separate axis), so all three match.
    assert set(resp.json()["ids"]) == {"p1", "p2", "p3"}


def test_bulk_routes_require_student_manage_and_validate() -> None:
    client, _ = _build()
    # A student token lacks student:manage.
    stu = _auth(_token(client, "p1"))
    status_body = {"student_ids": ["p1"], "status": "disabled"}
    del_body = {"student_ids": ["p1"]}
    assert client.post("/v1/students/bulk-status", headers=stu, json=status_body).status_code == 403
    assert client.post("/v1/students/bulk-delete", headers=stu, json=del_body).status_code == 403
    assert client.get("/v1/students/ids", headers=stu).status_code == 403
    # No token -> 401.
    assert client.post("/v1/students/bulk-status", json=status_body).status_code == 401
    assert client.post("/v1/students/bulk-delete", json=del_body).status_code == 401
    assert client.get("/v1/students/ids").status_code == 401
    # Empty student_ids -> 422 (schema min_length=1).
    sa = _auth(_token(client, "sa"))
    assert client.post(
        "/v1/students/bulk-status", headers=sa, json={"student_ids": [], "status": "disabled"}
    ).status_code == 422
    assert client.post(
        "/v1/students/bulk-delete", headers=sa, json={"student_ids": []}
    ).status_code == 422


@pytest.mark.parametrize("path", ["bulk-status", "bulk-delete"])
def test_bulk_routes_reject_over_the_cap(path: str) -> None:
    client, _ = _build()
    sa = _auth(_token(client, "sa"))
    ids = [f"x{i}" for i in range(1001)]  # over _MAX_BULK_IDS (1000)
    body: dict[str, object] = {"student_ids": ids}
    if path == "bulk-status":
        body["status"] = "disabled"
    assert client.post(f"/v1/students/{path}", headers=sa, json=body).status_code == 422


# ---- bulk-remove-class routes (BP27c) ----------------------------------


async def _seed_class_and_assign(
    container: SeededContainer, *, school_id: str, student_ids: list[str]
) -> str:
    """Create a class in ``school_id`` (via the container-wired ClassService, so the
    student↔class links are the same the routes exercise) and bulk-assign the given students to
    it; returns the new class id."""
    cls: StudentGroup = await container.class_service().create_class(
        school_id=school_id, name="3B", grade="3", section="B"
    )
    await container.class_service().assign_students(
        school_id=school_id, group_id=cls.id, student_ids=student_ids
    )
    return cls.id


async def test_bulk_remove_class_round_trip_clears_the_class() -> None:
    client, container = _build()
    await _seed_class_and_assign(container, school_id=_S1, student_ids=["p1", "p2", "p3"])
    sa = _auth(_token(client, "sa"))
    resp = client.post(
        "/v1/students/bulk-remove-class", headers=sa, json={"student_ids": ["p1", "p2"]}
    )
    assert resp.status_code == 200, resp.text
    assert {r["student_id"]: r["status"] for r in resp.json()["results"]} == {
        "p1": "ok",
        "p2": "ok",
    }
    # p1/p2 read no class; p3 (not selected) keeps it.
    assert client.get("/v1/students/p1", headers=sa).json()["student_group_id"] is None
    assert client.get("/v1/students/p2", headers=sa).json()["student_group_id"] is None
    assert client.get("/v1/students/p3", headers=sa).json()["student_group_id"] is not None


async def test_bulk_remove_class_mixed_ids_are_best_effort() -> None:
    client, container = _build()
    await _seed_class_and_assign(container, school_id=_S1, student_ids=["p1"])
    sa = _auth(_token(client, "sa"))
    resp = client.post(
        "/v1/students/bulk-remove-class", headers=sa, json={"student_ids": ["p1", "nope"]}
    )
    assert resp.status_code == 200, resp.text
    assert {r["student_id"]: r["status"] for r in resp.json()["results"]} == {
        "p1": "ok",
        "nope": "error",
    }
    assert client.get("/v1/students/p1", headers=sa).json()["student_group_id"] is None


async def test_bulk_remove_class_never_cross_tenant() -> None:
    # The s1 admin posts a REAL foreign-school (s2) student id (pf, assigned to an s2 class). It
    # comes back `error` (best-effort, p1 still clears) and pf keeps its class in s2 — inspected
    # with an s2 admin token.
    client, container = _build()
    await _seed_class_and_assign(container, school_id=_S1, student_ids=["p1"])
    await _seed_class_and_assign(container, school_id=_S2, student_ids=["pf"])
    sa = _auth(_token(client, "sa"))
    sa2 = _auth(_token(client, "sa2"))
    resp = client.post(
        "/v1/students/bulk-remove-class", headers=sa, json={"student_ids": ["pf", "p1"]}
    )
    assert resp.status_code == 200, resp.text
    assert {r["student_id"]: r["status"] for r in resp.json()["results"]} == {
        "pf": "error",
        "p1": "ok",
    }
    assert client.get("/v1/students/p1", headers=sa).json()["student_group_id"] is None
    # The foreign student's class pointer is untouched (still set in its own school).
    assert client.get("/v1/students/pf", headers=sa2).json()["student_group_id"] is not None


def test_bulk_remove_class_requires_student_manage_and_validates() -> None:
    client, _ = _build()
    body = {"student_ids": ["p1"]}
    # A student token lacks student:manage.
    stu = _auth(_token(client, "p1"))
    assert (
        client.post("/v1/students/bulk-remove-class", headers=stu, json=body).status_code == 403
    )
    # No token -> 401.
    assert client.post("/v1/students/bulk-remove-class", json=body).status_code == 401
    sa = _auth(_token(client, "sa"))
    # Empty -> 422 (schema min_length=1).
    assert (
        client.post(
            "/v1/students/bulk-remove-class", headers=sa, json={"student_ids": []}
        ).status_code
        == 422
    )
    # Over the cap -> 422.
    ids = [f"x{i}" for i in range(1001)]
    assert (
        client.post(
            "/v1/students/bulk-remove-class", headers=sa, json={"student_ids": ids}
        ).status_code
        == 422
    )


def test_bulk_remove_class_route_not_shadowed_by_wildcard() -> None:
    # Regression guard: POST /v1/students/bulk-remove-class must NOT be swallowed by the
    # /{student_id} routes (it's registered before them) — it returns the bulk envelope, not a 404
    # treating "bulk-remove-class" as a student id.
    client, _ = _build()
    sa = _auth(_token(client, "sa"))
    resp = client.post(
        "/v1/students/bulk-remove-class", headers=sa, json={"student_ids": ["p1"]}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["results"] == [{"student_id": "p1", "status": "ok"}]
