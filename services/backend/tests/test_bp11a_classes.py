"""BP11a — student classes: the ClassService + the class routes (decisions/0058).

Service-level class lifecycle (create/list-with-counts/update/delete-un-assigns) and student
assignment (single ``set_student_group`` + bulk ``assign_students``, both tenant-scoped), then
the routes end-to-end: the ``class:manage`` admin-only lifecycle vs the ``student:manage``
reads/assignment, the students-list class filter, cross-tenant 404s, and auth.
"""

from __future__ import annotations

import pytest
from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.domain.errors import NotFoundError, ValidationError
from backend.domain.models import (
    EnrollmentStatus,
    Role,
    School,
    Student,
    StudentGroup,
    User,
)
from backend.main import create_app
from backend.services.class_service import ClassService
from backend_fakes import (
    FakeSchoolRepo,
    FakeStudentGroupRepo,
    FakeStudentRepo,
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


# ---- service ----------------------------------------------------------


def _svc(
    *, groups: list[StudentGroup] | None = None, students: list[Student] | None = None
) -> tuple[ClassService, FakeStudentGroupRepo, FakeStudentRepo]:
    g = FakeStudentGroupRepo(groups or [])
    s = FakeStudentRepo(students or [])
    # Mirror the SeededContainer wiring so counts/names/cascade behave like the real join.
    s.link_groups(g.name_of)
    g.link_students(s.group_counts, on_delete=s.unassign_group)
    return ClassService(g, s), g, s


async def test_list_classes_includes_member_counts() -> None:
    svc, _, _ = _svc(
        groups=[
            make_student_group(id="c1", school_id=_S1, name="3A"),
            make_student_group(id="c2", school_id=_S1, name="3B"),
        ],
        students=[
            make_student(id="p1", school_id=_S1, student_group_id="c1"),
            make_student(id="p2", school_id=_S1, student_group_id="c1"),
            make_student(id="p3", school_id=_S1, student_group_id=None),  # un-classed
        ],
    )
    listings = await svc.list_classes(school_id=_S1)
    counts = {x.group.id: x.student_count for x in listings}
    assert counts == {"c1": 2, "c2": 0}


async def test_create_class_strips_and_requires_a_name() -> None:
    svc, _, _ = _svc()
    group = await svc.create_class(
        school_id=_S1, name="  Grade 3B  ", grade=" 3 ", section=""
    )
    assert group.name == "Grade 3B"
    assert group.grade == "3"
    assert group.section is None  # blank -> None
    with pytest.raises(ValidationError):
        await svc.create_class(school_id=_S1, name="   ", grade=None, section=None)


async def test_get_class_foreign_school_is_404() -> None:
    svc, _, _ = _svc(groups=[make_student_group(id="c1", school_id=_S1)])
    assert (await svc.get_class(school_id=_S1, group_id="c1")).id == "c1"
    with pytest.raises(NotFoundError):
        await svc.get_class(school_id=_S2, group_id="c1")


async def test_update_class_replaces_fields_and_404s_foreign() -> None:
    svc, _, _ = _svc(groups=[make_student_group(id="c1", school_id=_S1, name="old")])
    updated = await svc.update_class(
        school_id=_S1, group_id="c1", name="new", grade="4", section="A"
    )
    assert (updated.name, updated.grade, updated.section) == ("new", "4", "A")
    with pytest.raises(NotFoundError):
        await svc.update_class(
            school_id=_S2, group_id="c1", name="x", grade=None, section=None
        )


async def test_delete_class_unassigns_its_students() -> None:
    svc, _, students = _svc(
        groups=[make_student_group(id="c1", school_id=_S1)],
        students=[make_student(id="p1", school_id=_S1, student_group_id="c1")],
    )
    await svc.delete_class(school_id=_S1, group_id="c1")
    left = await students.get(_S1, "p1")
    assert left is not None and left.student_group_id is None  # SET NULL, not deleted


async def test_delete_foreign_class_is_404() -> None:
    svc, _, _ = _svc(groups=[make_student_group(id="c1", school_id=_S1)])
    with pytest.raises(NotFoundError):
        await svc.delete_class(school_id=_S2, group_id="c1")


async def test_assign_students_bulk_is_tenant_scoped() -> None:
    svc, _, students = _svc(
        groups=[make_student_group(id="c1", school_id=_S1)],
        students=[
            make_student(id="p1", school_id=_S1),
            make_student(id="p2", school_id=_S1),
            make_student(id="pf", school_id=_S2),  # foreign — must be skipped
        ],
    )
    assigned = await svc.assign_students(
        school_id=_S1, group_id="c1", student_ids=["p1", "p2", "pf"]
    )
    assert assigned == 2  # foreign student not counted/moved
    foreign = await students.get(_S2, "pf")
    assert foreign is not None and foreign.student_group_id is None


async def test_assign_students_to_foreign_class_is_404() -> None:
    svc, _, _ = _svc(
        groups=[make_student_group(id="c1", school_id=_S1)],
        students=[make_student(id="p1", school_id=_S1)],
    )
    with pytest.raises(NotFoundError):
        await svc.assign_students(school_id=_S2, group_id="c1", student_ids=["p1"])


async def test_set_student_group_assigns_and_carries_the_class_name() -> None:
    svc, _, _ = _svc(
        groups=[make_student_group(id="c1", school_id=_S1, name="Grade 3B")],
        students=[make_student(id="p1", school_id=_S1, student_group_id=None)],
    )
    updated = await svc.set_student_group(
        school_id=_S1, student_id="p1", group_id="c1"
    )
    assert updated.student_group_id == "c1"
    assert updated.student_group_name == "Grade 3B"


async def test_set_student_group_can_clear() -> None:
    svc, _, _ = _svc(
        groups=[make_student_group(id="c1", school_id=_S1)],
        students=[make_student(id="p1", school_id=_S1, student_group_id="c1")],
    )
    updated = await svc.set_student_group(school_id=_S1, student_id="p1", group_id=None)
    assert updated.student_group_id is None
    assert updated.student_group_name is None


async def test_set_student_group_foreign_student_is_404() -> None:
    svc, _, _ = _svc(
        groups=[make_student_group(id="c1", school_id=_S1)],
        students=[make_student(id="p1", school_id=_S2)],  # other school
    )
    with pytest.raises(NotFoundError):
        await svc.set_student_group(school_id=_S1, student_id="p1", group_id="c1")


async def test_set_student_group_foreign_class_is_404() -> None:
    svc, _, students = _svc(
        groups=[make_student_group(id="c1", school_id=_S2)],  # class in other school
        students=[make_student(id="p1", school_id=_S1)],
    )
    with pytest.raises(NotFoundError):
        await svc.set_student_group(school_id=_S1, student_id="p1", group_id="c1")
    # And the student was NOT moved (validation ran before the write).
    left = await students.get(_S1, "p1")
    assert left is not None and left.student_group_id is None


# ---- routes -----------------------------------------------------------

_HASHER = Argon2PasswordHasher()


def _user(*, id: str, role: Role, school_id: str | None) -> User:
    user: User = make_user(
        id=id,
        school_id=school_id,
        email=f"{id}@x.io",
        password_hash=_HASHER.hash("pw"),
        role=role,
    )
    return user


def _build(
    *,
    users: list[User],
    schools: list[School] | None = None,
    students: FakeStudentRepo | None = None,
    student_groups: FakeStudentGroupRepo | None = None,
) -> tuple[TestClient, SeededContainer]:
    container = SeededContainer(
        FakeUserRepo(users),
        FakeSchoolRepo(schools if schools is not None else [make_school(id=_S1)]),
        students=students or FakeStudentRepo(),
        student_groups=student_groups or FakeStudentGroupRepo(),
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


def _admin_client(
    *,
    students: FakeStudentRepo | None = None,
    student_groups: FakeStudentGroupRepo | None = None,
) -> tuple[TestClient, str]:
    client, _ = _build(
        users=[_user(id="sa", role=Role.SCHOOL_ADMIN, school_id=_S1)],
        students=students,
        student_groups=student_groups,
    )
    return client, _token(client, "sa")


def test_create_then_list_classes_with_counts() -> None:
    client, token = _admin_client()
    created = client.post(
        "/v1/classes",
        json={"name": "Grade 3B", "grade": "3", "section": "B"},
        headers=_auth(token),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Grade 3B" and body["grade"] == "3"

    listed = client.get("/v1/classes", headers=_auth(token))
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == body["id"] and items[0]["student_count"] == 0


def test_teacher_can_read_classes_but_not_create() -> None:
    # class:manage is admin-only; student:manage (teacher) reads + assigns.
    groups = FakeStudentGroupRepo([make_student_group(id="c1", school_id=_S1)])
    client, _ = _build(
        users=[_user(id="te", role=Role.TEACHER, school_id=_S1)],
        student_groups=groups,
    )
    token = _token(client, "te")
    assert client.get("/v1/classes", headers=_auth(token)).status_code == 200
    denied = client.post(
        "/v1/classes", json={"name": "X"}, headers=_auth(token)
    )
    assert denied.status_code == 403


def test_update_and_delete_class_are_admin_only() -> None:
    groups = FakeStudentGroupRepo([make_student_group(id="c1", school_id=_S1, name="old")])
    client, token = _admin_client(student_groups=groups)
    patched = client.patch(
        "/v1/classes/c1",
        json={"name": "new", "grade": "4", "section": "A"},
        headers=_auth(token),
    )
    assert patched.status_code == 200 and patched.json()["name"] == "new"
    deleted = client.delete("/v1/classes/c1", headers=_auth(token))
    assert deleted.status_code == 204
    assert client.get("/v1/classes/c1", headers=_auth(token)).status_code == 404


def test_class_lifecycle_is_tenant_isolated() -> None:
    # An admin of s2 cannot see/patch/delete a class of s1 (404, never a cross-tenant touch).
    groups = FakeStudentGroupRepo([make_student_group(id="c1", school_id=_S1)])
    client, _ = _build(
        users=[_user(id="sa2", role=Role.SCHOOL_ADMIN, school_id=_S2)],
        schools=[make_school(id=_S1), make_school(id=_S2)],
        student_groups=groups,
    )
    token = _token(client, "sa2")
    assert client.get("/v1/classes/c1", headers=_auth(token)).status_code == 404
    assert (
        client.patch(
            "/v1/classes/c1", json={"name": "hax"}, headers=_auth(token)
        ).status_code
        == 404
    )
    assert client.delete("/v1/classes/c1", headers=_auth(token)).status_code == 404


def test_assign_students_via_route() -> None:
    groups = FakeStudentGroupRepo([make_student_group(id="c1", school_id=_S1)])
    students = FakeStudentRepo(
        [
            make_student(id="p1", school_id=_S1),
            make_student(id="p2", school_id=_S1),
        ]
    )
    client, token = _admin_client(students=students, student_groups=groups)
    resp = client.post(
        "/v1/classes/c1/members",
        json={"student_ids": ["p1", "p2"]},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["assigned"] == 2


def test_set_student_class_via_patch_and_clear() -> None:
    groups = FakeStudentGroupRepo(
        [make_student_group(id="c1", school_id=_S1, name="Grade 3B")]
    )
    students = FakeStudentRepo([make_student(id="p1", school_id=_S1)])
    client, token = _admin_client(students=students, student_groups=groups)

    assigned = client.patch(
        "/v1/students/p1", json={"student_group_id": "c1"}, headers=_auth(token)
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["student_group_id"] == "c1"
    assert assigned.json()["student_group_name"] == "Grade 3B"

    cleared = client.patch(
        "/v1/students/p1", json={"student_group_id": None}, headers=_auth(token)
    )
    assert cleared.status_code == 200
    assert cleared.json()["student_group_id"] is None


def test_patch_student_to_a_foreign_class_is_404() -> None:
    groups = FakeStudentGroupRepo([make_student_group(id="c1", school_id=_S2)])
    students = FakeStudentRepo([make_student(id="p1", school_id=_S1)])
    client, token = _admin_client(students=students, student_groups=groups)
    resp = client.patch(
        "/v1/students/p1", json={"student_group_id": "c1"}, headers=_auth(token)
    )
    assert resp.status_code == 404


def test_patch_student_empty_body_is_422() -> None:
    # student_group_id is required-but-nullable — a {} body can't silently un-assign.
    students = FakeStudentRepo([make_student(id="p1", school_id=_S1)])
    client, token = _admin_client(students=students)
    resp = client.patch("/v1/students/p1", json={}, headers=_auth(token))
    assert resp.status_code == 422


def test_students_list_filters_by_class() -> None:
    students = FakeStudentRepo(
        [
            make_student(id="p1", school_id=_S1, name="A", student_group_id="c1"),
            make_student(id="p2", school_id=_S1, name="B", student_group_id="c2"),
            make_student(id="p3", school_id=_S1, name="C", student_group_id=None),
        ]
    )
    client, token = _admin_client(students=students)
    resp = client.get(
        "/v1/students", params={"student_group_id": "c1"}, headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    ids = [x["id"] for x in resp.json()["items"]]
    assert ids == ["p1"]


def test_class_routes_require_auth() -> None:
    client, _ = _build(users=[_user(id="sa", role=Role.SCHOOL_ADMIN, school_id=_S1)])
    assert client.get("/v1/classes").status_code == 401
    assert client.post("/v1/classes", json={"name": "X"}).status_code == 401
    assert client.patch("/v1/students/p1", json={"student_group_id": None}).status_code == 401


def test_patch_student_requires_student_manage() -> None:
    client, _ = _build(users=[_user(id="stu", role=Role.STUDENT, school_id=_S1)])
    token = _token(client, "stu")
    resp = client.patch(
        "/v1/students/p1", json={"student_group_id": None}, headers=_auth(token)
    )
    assert resp.status_code == 403


def test_class_lifecycle_routes_reject_a_teacher_but_allow_assignment() -> None:
    # PATCH + DELETE ride on class:manage (admin only) → 403 for a teacher; the bulk-assign
    # /members rides on student:manage → a teacher CAN assign. Guards the intentional split
    # against a regression that up/downgrades either dep.
    groups = FakeStudentGroupRepo([make_student_group(id="c1", school_id=_S1)])
    students = FakeStudentRepo([make_student(id="p1", school_id=_S1)])
    client, _ = _build(
        users=[_user(id="te", role=Role.TEACHER, school_id=_S1)],
        students=students,
        student_groups=groups,
    )
    token = _token(client, "te")
    assert (
        client.patch("/v1/classes/c1", json={"name": "x"}, headers=_auth(token)).status_code
        == 403
    )
    assert client.delete("/v1/classes/c1", headers=_auth(token)).status_code == 403
    ok = client.post(
        "/v1/classes/c1/members", json={"student_ids": ["p1"]}, headers=_auth(token)
    )
    assert ok.status_code == 200 and ok.json()["assigned"] == 1


def test_create_class_with_a_blank_name_is_rejected() -> None:
    client, token = _admin_client()
    # "" fails the schema's min_length=1 → 422; "   " passes it but the service strip-guard
    # rejects it → 400 (the one thing min_length can't catch).
    assert client.post("/v1/classes", json={"name": ""}, headers=_auth(token)).status_code == 422
    blank = client.post("/v1/classes", json={"name": "   "}, headers=_auth(token))
    assert blank.status_code == 400


def test_create_name_only_class_round_trips_with_null_grade_and_section() -> None:
    # The realistic default (the FE sends null grade/section when blank) — untested elsewhere.
    client, token = _admin_client()
    created = client.post("/v1/classes", json={"name": "Homeroom"}, headers=_auth(token))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["grade"] is None and body["section"] is None
    item = client.get("/v1/classes", headers=_auth(token)).json()["items"][0]
    assert item["name"] == "Homeroom" and item["student_count"] == 0


def test_students_class_filter_combines_with_status_and_count_sort() -> None:
    # The class filter ANDs with status AND threads through the count-sort id-scan path
    # (ListingService.list_ids), not just the row-native path.
    students = FakeStudentRepo(
        [
            make_student(
                id="p1",
                school_id=_S1,
                name="A",
                student_group_id="c1",
                enrollment_status=EnrollmentStatus.ENROLLED,
            ),
            make_student(
                id="p2",
                school_id=_S1,
                name="B",
                student_group_id="c1",
                enrollment_status=EnrollmentStatus.PENDING,
            ),
            make_student(
                id="p3",
                school_id=_S1,
                name="C",
                student_group_id="c2",
                enrollment_status=EnrollmentStatus.ENROLLED,
            ),
        ]
    )
    client, token = _admin_client(students=students)
    combo = client.get(
        "/v1/students",
        params={"student_group_id": "c1", "status": "enrolled"},
        headers=_auth(token),
    )
    assert combo.status_code == 200
    assert [x["id"] for x in combo.json()["items"]] == ["p1"]

    # class + a count-column sort → the id-scan path filtered to the class.
    sorted_resp = client.get(
        "/v1/students",
        params={"student_group_id": "c1", "sort": "appearance_count", "dir": "desc"},
        headers=_auth(token),
    )
    assert sorted_resp.status_code == 200
    assert {x["id"] for x in sorted_resp.json()["items"]} == {"p1", "p2"}
