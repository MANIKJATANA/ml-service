"""BP11c — teacher delegation: the DelegationService + the delegation routes + the list
"focus" scope + the event↔class tag (decisions/0060).

Service-level teacher↔class assignment (assign/list/remove from the class side, list/set from
the teacher side, both tenant-scoped, foreign class/non-teacher → 404, foreign ids skipped) and
the caller's own "my classes"; then the routes end-to-end — the ``class:manage`` admin-only
delegation vs the teacher's read-only ``/mine`` + ``mine=true`` focus, the students/events focus
scope (a teacher sees only their classes; events also include untagged school-wide), the event
class tag/filter + foreign-class 404, class-delete un-tags events, cross-tenant 404s, and auth.
"""

from __future__ import annotations

import pytest
from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.domain.errors import NotFoundError
from backend.domain.models import Role, School, StudentGroup, User
from backend.main import create_app
from backend.services.delegation_service import DelegationService
from backend_fakes import (
    FakeEventRepo,
    FakeSchoolRepo,
    FakeStudentGroupRepo,
    FakeStudentRepo,
    FakeTeacherClassRepo,
    FakeUserRepo,
    SeededContainer,
    make_event,
    make_school,
    make_student,
    make_student_group,
    make_user,
)
from fastapi.testclient import TestClient

_S1 = "s1"
_S2 = "s2"


# ---- service ----------------------------------------------------------


def _del_svc(
    *,
    groups: list[StudentGroup] | None = None,
    users: list[User] | None = None,
    links: list[tuple[str, str, str]] | None = None,
) -> tuple[DelegationService, FakeTeacherClassRepo]:
    links_repo = FakeTeacherClassRepo(links or [])
    g = FakeStudentGroupRepo(groups or [])
    u = FakeUserRepo(users or [])
    return DelegationService(links_repo, g, u), links_repo


def _teacher(id: str, school_id: str = _S1) -> User:
    user: User = make_user(
        id=id, school_id=school_id, email=f"{id}@x.io", role=Role.TEACHER
    )
    return user


async def test_assign_teachers_links_and_is_idempotent() -> None:
    svc, links = _del_svc(
        groups=[make_student_group(id="c1", school_id=_S1)],
        users=[_teacher("t1"), _teacher("t2")],
    )
    n = await svc.assign_teachers(
        school_id=_S1, group_id="c1", teacher_ids=["t1", "t2"]
    )
    assert n == 2
    # Idempotent — re-assigning the same pair is a no-op, still counted as "valid".
    again = await svc.assign_teachers(school_id=_S1, group_id="c1", teacher_ids=["t1"])
    assert again == 1
    assert set(await links.list_teacher_ids_for_group(_S1, "c1")) == {"t1", "t2"}


async def test_assign_teachers_skips_foreign_and_non_teacher() -> None:
    svc, links = _del_svc(
        groups=[make_student_group(id="c1", school_id=_S1)],
        users=[
            _teacher("t1"),
            _teacher("tf", school_id=_S2),  # foreign school — skipped
            make_user(id="ad", school_id=_S1, email="ad@x.io", role=Role.SCHOOL_ADMIN),
        ],
    )
    n = await svc.assign_teachers(
        school_id=_S1, group_id="c1", teacher_ids=["t1", "tf", "ad", "ghost"]
    )
    assert n == 1  # only the in-school teacher t1
    assert await links.list_teacher_ids_for_group(_S1, "c1") == ["t1"]


async def test_assign_teachers_to_foreign_class_is_404() -> None:
    svc, _ = _del_svc(
        groups=[make_student_group(id="c1", school_id=_S1)], users=[_teacher("t1")]
    )
    with pytest.raises(NotFoundError):
        await svc.assign_teachers(school_id=_S2, group_id="c1", teacher_ids=["t1"])


async def test_remove_class_teacher_and_missing_link_is_404() -> None:
    svc, _ = _del_svc(
        groups=[make_student_group(id="c1", school_id=_S1)],
        users=[_teacher("t1")],
        links=[(_S1, "t1", "c1")],
    )
    await svc.remove_class_teacher(school_id=_S1, group_id="c1", teacher_id="t1")
    with pytest.raises(NotFoundError):  # link now gone
        await svc.remove_class_teacher(school_id=_S1, group_id="c1", teacher_id="t1")


async def test_list_class_teachers_returns_assigned_users() -> None:
    svc, _ = _del_svc(
        groups=[make_student_group(id="c1", school_id=_S1)],
        users=[_teacher("t1"), _teacher("t2")],
        links=[(_S1, "t1", "c1")],
    )
    teachers = await svc.list_class_teachers(school_id=_S1, group_id="c1")
    assert [t.id for t in teachers] == ["t1"]


async def test_list_class_teachers_foreign_class_is_404() -> None:
    svc, _ = _del_svc(groups=[make_student_group(id="c1", school_id=_S1)])
    with pytest.raises(NotFoundError):
        await svc.list_class_teachers(school_id=_S2, group_id="c1")


async def test_set_teacher_classes_replaces_and_skips_foreign() -> None:
    svc, links = _del_svc(
        groups=[
            make_student_group(id="c1", school_id=_S1),
            make_student_group(id="c2", school_id=_S1),
            make_student_group(id="cf", school_id=_S2),  # foreign — skipped
        ],
        users=[_teacher("t1")],
        links=[(_S1, "t1", "c1")],  # replaced by the call below
    )
    result = await svc.set_teacher_classes(
        school_id=_S1, teacher_id="t1", group_ids=["c2", "cf"]
    )
    assert {g.id for g in result} == {"c2"}  # cf skipped, c1 replaced away
    assert set(await links.list_group_ids_for_teacher(_S1, "t1")) == {"c2"}


async def test_set_teacher_classes_empty_clears() -> None:
    svc, links = _del_svc(
        groups=[make_student_group(id="c1", school_id=_S1)],
        users=[_teacher("t1")],
        links=[(_S1, "t1", "c1")],
    )
    result = await svc.set_teacher_classes(school_id=_S1, teacher_id="t1", group_ids=[])
    assert result == []
    assert await links.list_group_ids_for_teacher(_S1, "t1") == []


async def test_teacher_side_reads_require_a_real_in_school_teacher() -> None:
    svc, _ = _del_svc(
        groups=[make_student_group(id="c1", school_id=_S1)],
        users=[
            _teacher("t1"),
            make_user(id="ad", school_id=_S1, email="ad@x.io", role=Role.SCHOOL_ADMIN),
        ],
    )
    with pytest.raises(NotFoundError):  # foreign school
        await svc.list_teacher_classes(school_id=_S2, teacher_id="t1")
    with pytest.raises(NotFoundError):  # wrong role (an admin isn't a delegatable teacher)
        await svc.set_teacher_classes(school_id=_S1, teacher_id="ad", group_ids=[])


async def test_my_group_ids_is_the_callers_own_scope() -> None:
    svc, _ = _del_svc(
        groups=[make_student_group(id="c1", school_id=_S1)],
        users=[_teacher("t1")],
        links=[(_S1, "t1", "c1"), (_S1, "t2", "c1")],
    )
    assert await svc.my_group_ids(school_id=_S1, teacher_id="t1") == ["c1"]
    assert await svc.my_group_ids(school_id=_S1, teacher_id="nobody") == []


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
    teacher_classes: FakeTeacherClassRepo | None = None,
    events: FakeEventRepo | None = None,
) -> tuple[TestClient, SeededContainer]:
    container = SeededContainer(
        FakeUserRepo(users),
        FakeSchoolRepo(schools if schools is not None else [make_school(id=_S1)]),
        students=students or FakeStudentRepo(),
        student_groups=student_groups or FakeStudentGroupRepo(),
        teacher_classes=teacher_classes or FakeTeacherClassRepo(),
        events=events or FakeEventRepo(),
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


def _admin_and_teacher() -> list[User]:
    return [
        _user(id="sa", role=Role.SCHOOL_ADMIN, school_id=_S1),
        _user(id="te", role=Role.TEACHER, school_id=_S1),
    ]


# ---- delegation routes (admin-only) -----------------------------------


def test_assign_list_remove_class_teachers_via_routes() -> None:
    groups = FakeStudentGroupRepo([make_student_group(id="c1", school_id=_S1)])
    client, _ = _build(users=_admin_and_teacher(), student_groups=groups)
    token = _token(client, "sa")

    assigned = client.post(
        "/v1/classes/c1/teachers", json={"teacher_ids": ["te"]}, headers=_auth(token)
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["assigned"] == 1

    listed = client.get("/v1/classes/c1/teachers", headers=_auth(token))
    assert listed.status_code == 200
    assert [t["id"] for t in listed.json()] == ["te"]

    removed = client.delete("/v1/classes/c1/teachers/te", headers=_auth(token))
    assert removed.status_code == 204
    assert client.get("/v1/classes/c1/teachers", headers=_auth(token)).json() == []


def test_set_and_list_teacher_classes_via_staff_routes() -> None:
    groups = FakeStudentGroupRepo(
        [
            make_student_group(id="c1", school_id=_S1, name="3A"),
            make_student_group(id="c2", school_id=_S1, name="3B"),
        ]
    )
    client, _ = _build(users=_admin_and_teacher(), student_groups=groups)
    token = _token(client, "sa")

    put = client.put(
        "/v1/staff/te/classes", json={"group_ids": ["c1", "c2"]}, headers=_auth(token)
    )
    assert put.status_code == 200, put.text
    assert {c["id"] for c in put.json()["items"]} == {"c1", "c2"}

    got = client.get("/v1/staff/te/classes", headers=_auth(token))
    assert got.status_code == 200
    assert {c["id"] for c in got.json()["items"]} == {"c1", "c2"}


def test_delegation_routes_reject_a_teacher() -> None:
    # Assigning teachers to classes is class:manage (admin-only) — a teacher gets 403.
    groups = FakeStudentGroupRepo([make_student_group(id="c1", school_id=_S1)])
    client, _ = _build(users=_admin_and_teacher(), student_groups=groups)
    token = _token(client, "te")
    assert (
        client.post(
            "/v1/classes/c1/teachers", json={"teacher_ids": ["te"]}, headers=_auth(token)
        ).status_code
        == 403
    )
    assert client.get("/v1/classes/c1/teachers", headers=_auth(token)).status_code == 403
    assert client.put(
        "/v1/staff/te/classes", json={"group_ids": []}, headers=_auth(token)
    ).status_code == 403


def test_delegation_is_tenant_isolated() -> None:
    # An admin of s2 can't assign/list a class of s1 (404, never a cross-tenant link).
    groups = FakeStudentGroupRepo([make_student_group(id="c1", school_id=_S1)])
    client, _ = _build(
        users=[_user(id="sa2", role=Role.SCHOOL_ADMIN, school_id=_S2)],
        schools=[make_school(id=_S1), make_school(id=_S2)],
        student_groups=groups,
    )
    token = _token(client, "sa2")
    assert (
        client.post(
            "/v1/classes/c1/teachers", json={"teacher_ids": ["x"]}, headers=_auth(token)
        ).status_code
        == 404
    )
    assert client.get("/v1/classes/c1/teachers", headers=_auth(token)).status_code == 404


# ---- the teacher's own "my classes" + focus scope ---------------------


def test_my_classes_route_lists_only_the_callers_classes() -> None:
    groups = FakeStudentGroupRepo(
        [
            make_student_group(id="c1", school_id=_S1, name="3A"),
            make_student_group(id="c2", school_id=_S1, name="3B"),
        ]
    )
    links = FakeTeacherClassRepo([(_S1, "te", "c1")])
    client, _ = _build(
        users=_admin_and_teacher(), student_groups=groups, teacher_classes=links
    )
    token = _token(client, "te")
    resp = client.get("/v1/classes/mine", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert [c["id"] for c in resp.json()["items"]] == ["c1"]


def test_students_focus_scopes_a_teacher_to_their_classes() -> None:
    students = FakeStudentRepo(
        [
            make_student(id="p1", school_id=_S1, name="A", student_group_id="c1"),
            make_student(id="p2", school_id=_S1, name="B", student_group_id="c2"),
            make_student(id="p3", school_id=_S1, name="C", student_group_id=None),
        ]
    )
    groups = FakeStudentGroupRepo([make_student_group(id="c1", school_id=_S1)])
    links = FakeTeacherClassRepo([(_S1, "te", "c1")])
    client, _ = _build(
        users=_admin_and_teacher(),
        students=students,
        student_groups=groups,
        teacher_classes=links,
    )
    token = _token(client, "te")
    # Focus on: only c1's students. An un-classed student is in no teacher's scope.
    focused = client.get("/v1/students", params={"mine": "true"}, headers=_auth(token))
    assert focused.status_code == 200, focused.text
    assert [x["id"] for x in focused.json()["items"]] == ["p1"]
    # Focus off (default): the whole school.
    everyone = client.get("/v1/students", headers=_auth(token))
    assert {x["id"] for x in everyone.json()["items"]} == {"p1", "p2", "p3"}


def test_admin_mine_is_ignored_sees_everyone() -> None:
    students = FakeStudentRepo(
        [make_student(id="p1", school_id=_S1, student_group_id="c1")]
    )
    client, _ = _build(users=_admin_and_teacher(), students=students)
    token = _token(client, "sa")  # an admin with mine=true still sees all
    resp = client.get("/v1/students", params={"mine": "true"}, headers=_auth(token))
    assert resp.status_code == 200
    assert [x["id"] for x in resp.json()["items"]] == ["p1"]


def test_events_focus_includes_class_events_plus_untagged() -> None:
    events = FakeEventRepo(
        [
            make_event(id="e1", school_id=_S1, name="Cls", student_group_id="c1"),
            make_event(id="e2", school_id=_S1, name="Other", student_group_id="c2"),
            make_event(id="e3", school_id=_S1, name="Assembly"),  # untagged/school-wide
        ]
    )
    groups = FakeStudentGroupRepo([make_student_group(id="c1", school_id=_S1)])
    links = FakeTeacherClassRepo([(_S1, "te", "c1")])
    client, _ = _build(
        users=_admin_and_teacher(),
        student_groups=groups,
        teacher_classes=links,
        events=events,
    )
    token = _token(client, "te")
    focused = client.get("/v1/events", params={"mine": "true"}, headers=_auth(token))
    assert focused.status_code == 200, focused.text
    # c1's event + the untagged school-wide event; NOT c2's event.
    assert {x["id"] for x in focused.json()["items"]} == {"e1", "e3"}


def test_teacher_with_no_classes_focus_sees_no_students_but_untagged_events() -> None:
    students = FakeStudentRepo(
        [make_student(id="p1", school_id=_S1, student_group_id="c1")]
    )
    events = FakeEventRepo(
        [
            make_event(id="e1", school_id=_S1, student_group_id="c1"),
            make_event(id="e2", school_id=_S1),  # untagged
        ]
    )
    client, _ = _build(users=_admin_and_teacher(), students=students, events=events)
    token = _token(client, "te")  # te has NO assigned classes
    s = client.get("/v1/students", params={"mine": "true"}, headers=_auth(token))
    assert s.json()["items"] == []  # no classes → no students
    e = client.get("/v1/events", params={"mine": "true"}, headers=_auth(token))
    assert [x["id"] for x in e.json()["items"]] == ["e2"]  # only the untagged event


def test_focus_threads_through_the_count_sort_path() -> None:
    # A count-column sort (students by appearances / events by photos) takes the ListingService
    # id-scan path, NOT the row-native one — verify the focus scope is applied there too.
    students = FakeStudentRepo(
        [
            make_student(id="p1", school_id=_S1, name="A", student_group_id="c1"),
            make_student(id="p2", school_id=_S1, name="B", student_group_id="c2"),
        ]
    )
    events = FakeEventRepo(
        [
            make_event(id="e1", school_id=_S1, name="Cls", student_group_id="c1"),
            make_event(id="e2", school_id=_S1, name="Other", student_group_id="c2"),
            make_event(id="e3", school_id=_S1, name="Assembly"),  # untagged
        ]
    )
    groups = FakeStudentGroupRepo([make_student_group(id="c1", school_id=_S1)])
    links = FakeTeacherClassRepo([(_S1, "te", "c1")])
    client, _ = _build(
        users=_admin_and_teacher(),
        students=students,
        student_groups=groups,
        teacher_classes=links,
        events=events,
    )
    token = _token(client, "te")
    s = client.get(
        "/v1/students",
        params={"mine": "true", "sort": "appearance_count", "dir": "desc"},
        headers=_auth(token),
    )
    assert s.status_code == 200
    assert [x["id"] for x in s.json()["items"]] == ["p1"]
    e = client.get(
        "/v1/events",
        params={"mine": "true", "sort": "media_count", "dir": "desc"},
        headers=_auth(token),
    )
    assert e.status_code == 200
    assert {x["id"] for x in e.json()["items"]} == {"e1", "e3"}


# ---- event↔class tag --------------------------------------------------


def test_create_and_filter_event_by_class() -> None:
    groups = FakeStudentGroupRepo(
        [make_student_group(id="c1", school_id=_S1, name="Grade 3B")]
    )
    events = FakeEventRepo()
    client, _ = _build(
        users=_admin_and_teacher(), student_groups=groups, events=events
    )
    token = _token(client, "sa")
    created = client.post(
        "/v1/events",
        json={"name": "Trip", "student_group_id": "c1"},
        headers=_auth(token),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["student_group_id"] == "c1"
    assert body["student_group_name"] == "Grade 3B"

    filtered = client.get(
        "/v1/events", params={"student_group_id": "c1"}, headers=_auth(token)
    )
    assert [x["id"] for x in filtered.json()["items"]] == [body["id"]]


def test_create_event_with_foreign_class_is_404() -> None:
    groups = FakeStudentGroupRepo([make_student_group(id="c1", school_id=_S2)])
    client, _ = _build(
        users=_admin_and_teacher(),
        schools=[make_school(id=_S1), make_school(id=_S2)],
        student_groups=groups,
    )
    token = _token(client, "sa")
    resp = client.post(
        "/v1/events",
        json={"name": "Trip", "student_group_id": "c1"},
        headers=_auth(token),
    )
    assert resp.status_code == 404


def test_deleting_a_class_untags_its_events() -> None:
    # events.student_group_id is ON DELETE SET NULL — deleting a class un-tags its events,
    # never deletes them (the FakeEventRepo cascade mirrors the FK).
    groups = FakeStudentGroupRepo([make_student_group(id="c1", school_id=_S1)])
    events = FakeEventRepo(
        [make_event(id="e1", school_id=_S1, name="Trip", student_group_id="c1")]
    )
    client, _ = _build(
        users=_admin_and_teacher(), student_groups=groups, events=events
    )
    token = _token(client, "sa")
    assert client.delete("/v1/classes/c1", headers=_auth(token)).status_code == 204
    got = client.get("/v1/events/e1", headers=_auth(token))
    assert got.status_code == 200
    assert got.json()["student_group_id"] is None  # un-tagged, not deleted


def test_update_event_sets_the_class() -> None:
    groups = FakeStudentGroupRepo(
        [make_student_group(id="c1", school_id=_S1, name="Grade 3B")]
    )
    events = FakeEventRepo([make_event(id="e1", school_id=_S1, name="Trip")])
    client, _ = _build(
        users=_admin_and_teacher(), student_groups=groups, events=events
    )
    token = _token(client, "sa")
    patched = client.patch(
        "/v1/events/e1", json={"student_group_id": "c1"}, headers=_auth(token)
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["student_group_id"] == "c1"
    assert patched.json()["student_group_name"] == "Grade 3B"


# ---- auth -------------------------------------------------------------


def test_delegation_routes_require_auth() -> None:
    client, _ = _build(users=_admin_and_teacher())
    assert client.get("/v1/classes/mine").status_code == 401
    assert client.get("/v1/classes/c1/teachers").status_code == 401
    assert client.post("/v1/classes/c1/teachers", json={"teacher_ids": ["x"]}).status_code == 401
    assert client.put("/v1/staff/te/classes", json={"group_ids": []}).status_code == 401
