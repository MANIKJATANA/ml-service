"""BP24a — two-way doors (decisions/0079).

The backend "doors": clearable event tags (the 0027 revision — an explicit-null PATCH clears
category/term/class, an omitted field leaves them unchanged, a value sets them, a foreign id
still 404s) + classes at CSV scale (an optional class column on the bulk import auto-creates/
assigns; a paste-emails endpoint resolves + bulk-assigns, reporting the unmatched).
"""

from __future__ import annotations

import pytest
from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.domain.errors import NotFoundError
from backend.domain.models import (
    Event,
    EventCategory,
    Role,
    Student,
    StudentGroup,
    User,
)
from backend.main import create_app
from backend.services.class_service import ClassService
from backend.services.event_service import EventService
from backend.services.student_service import StudentService
from backend_fakes import (
    FakeEventCategoryRepo,
    FakeEventJobProducer,
    FakeEventRepo,
    FakeHasher,
    FakeMediaRepo,
    FakeMlClient,
    FakeObjectStore,
    FakeSchoolRepo,
    FakeStudentGroupRepo,
    FakeStudentRepo,
    FakeThumbnailer,
    FakeUserRepo,
    SeededContainer,
    make_event,
    make_event_category,
    make_school,
    make_student,
    make_student_group,
    make_user,
)
from fastapi.testclient import TestClient

_S1 = "s1"
_HASHER = Argon2PasswordHasher()


# ======================================================================
# slice 1 · clearable event tags
# ======================================================================


def _event_svc(
    *,
    events: list[Event] | None = None,
    categories: list[EventCategory] | None = None,
    groups: list[StudentGroup] | None = None,
) -> tuple[EventService, FakeEventRepo]:
    erepo = FakeEventRepo(events or [])
    crepo = FakeEventCategoryRepo(categories or [])
    grepo = FakeStudentGroupRepo(groups or [])
    erepo.link_categories(crepo.name_of)
    erepo.link_groups(grepo.name_of)
    svc = EventService(
        erepo, FakeMediaRepo(), FakeEventJobProducer(), crepo, grepo, FakeUserRepo()
    )
    return svc, erepo


def _tagged_event() -> Event:
    event: Event = make_event(
        id="e1", school_id=_S1,
        category_id="cat-1", category_name="Sports",
        term="Fall 2026",
        student_group_id="cls-1", student_group_name="Grade 3B",
    )
    return event


async def test_update_event_clears_tags_on_explicit_none() -> None:
    """An explicit None on the three tag fields clears them (the 0027 revision)."""
    svc, _ = _event_svc(
        events=[_tagged_event()],
        categories=[make_event_category(id="cat-1", school_id=_S1, name="Sports")],
        groups=[make_student_group(id="cls-1", school_id=_S1, name="Grade 3B")],
    )
    updated = await svc.update_event(
        school_id=_S1, event_id="e1",
        category_id=None, term=None, student_group_id=None,
    )
    assert updated.category_id is None and updated.category_name is None
    assert updated.term is None
    assert updated.student_group_id is None and updated.student_group_name is None


async def test_update_event_unset_leaves_tags_unchanged() -> None:
    """A tag field NOT passed (default UNSET) is left exactly as-is; only name changes."""
    svc, _ = _event_svc(
        events=[_tagged_event()],
        categories=[make_event_category(id="cat-1", school_id=_S1, name="Sports")],
        groups=[make_student_group(id="cls-1", school_id=_S1, name="Grade 3B")],
    )
    updated = await svc.update_event(school_id=_S1, event_id="e1", name="Renamed")
    assert updated.name == "Renamed"
    assert updated.category_id == "cat-1"  # untouched
    assert updated.term == "Fall 2026"
    assert updated.student_group_id == "cls-1"


async def test_update_event_sets_tag_to_new_value() -> None:
    svc, _ = _event_svc(
        events=[_tagged_event()],
        categories=[
            make_event_category(id="cat-1", school_id=_S1, name="Sports"),
            make_event_category(id="cat-2", school_id=_S1, name="Arts"),
        ],
        groups=[make_student_group(id="cls-1", school_id=_S1, name="Grade 3B")],
    )
    updated = await svc.update_event(school_id=_S1, event_id="e1", category_id="cat-2")
    assert updated.category_id == "cat-2" and updated.category_name == "Arts"
    assert updated.term == "Fall 2026"  # other tags untouched


async def test_update_event_foreign_tag_still_404s() -> None:
    """Setting a tag to a foreign/unknown id is still a 404 (clearing/UNSET skip validation)."""
    svc, _ = _event_svc(
        events=[make_event(id="e1", school_id=_S1)], categories=[], groups=[]
    )
    with pytest.raises(NotFoundError):
        await svc.update_event(school_id=_S1, event_id="e1", category_id="ghost")
    with pytest.raises(NotFoundError):
        await svc.update_event(school_id=_S1, event_id="e1", student_group_id="ghost")


# ======================================================================
# slice 3a · CSV class column
# ======================================================================


def _student_svc(*, groups: FakeStudentGroupRepo) -> tuple[StudentService, FakeStudentRepo]:
    srepo = FakeSchoolRepo([make_school(id=_S1, max_teachers=5)])
    urepo = FakeUserRepo([])
    strepo = FakeStudentRepo()
    urepo.link_cascade(strepo.remove_by_user)
    strepo.link_users(urepo.email_of)
    strepo.link_groups(groups.name_of)
    svc = StudentService(
        strepo, urepo, srepo, FakeHasher(), FakeObjectStore(), FakeMlClient(),
        FakeThumbnailer(), groups, reference_photo_prefix="reference-photos",
    )
    return svc, strepo


async def test_bulk_import_auto_creates_and_assigns_class() -> None:
    grepo = FakeStudentGroupRepo()
    svc, strepo = _student_svc(groups=grepo)
    results = await svc.bulk_create_students(
        school_id=_S1,
        rows=[
            ("Ann", "ann@x.io", "Grade 3B"),
            ("Bob", "bob@x.io", "grade 3b"),  # same class (case-insensitive) → reused
            ("Cy", "cy@x.io", "Grade 4A"),
            ("Di", "di@x.io", None),  # no class
        ],
    )
    assert [r.status for r in results] == ["created"] * 4
    # Two distinct classes created (3B deduped across the two casings), never one per row.
    classes = await grepo.list_by_school(_S1)
    assert {g.name for g in classes} == {"Grade 3B", "Grade 4A"}
    students = {s.name: s for s in await strepo.list_by_school(_S1)}
    assert students["Ann"].student_group_name == "Grade 3B"
    assert students["Bob"].student_group_id == students["Ann"].student_group_id  # same class
    assert students["Cy"].student_group_name == "Grade 4A"
    assert students["Di"].student_group_id is None  # no class column value


async def test_bulk_import_without_class_column_creates_no_classes() -> None:
    """Back-compat: a CSV with no class column (all None) creates no classes."""
    grepo = FakeStudentGroupRepo()
    svc, strepo = _student_svc(groups=grepo)
    results = await svc.bulk_create_students(
        school_id=_S1, rows=[("Ann", "ann@x.io", None), ("Bob", "bob@x.io", None)]
    )
    assert [r.status for r in results] == ["created", "created"]
    assert await grepo.list_by_school(_S1) == []
    assert all(s.student_group_id is None for s in await strepo.list_by_school(_S1))


async def test_bulk_import_reuses_an_existing_class_by_name() -> None:
    grepo = FakeStudentGroupRepo([make_student_group(id="cls-1", school_id=_S1, name="Grade 3B")])
    svc, strepo = _student_svc(groups=grepo)
    await svc.bulk_create_students(
        school_id=_S1, rows=[("Ann", "ann@x.io", "grade 3b")]
    )
    # No new class — the existing "Grade 3B" is reused (case-insensitive); the student joins it.
    assert len(await grepo.list_by_school(_S1)) == 1
    ann = (await strepo.list_by_school(_S1))[0]
    assert ann.student_group_id == "cls-1"


# ======================================================================
# slice 3b · paste-emails bulk assign
# ======================================================================


def _class_svc(
    *, groups: list[StudentGroup] | None = None, students: list[Student] | None = None
) -> tuple[ClassService, FakeStudentGroupRepo, FakeStudentRepo]:
    grepo = FakeStudentGroupRepo(groups or [])
    strepo = FakeStudentRepo(students or [])
    strepo.link_groups(grepo.name_of)
    return ClassService(grepo, strepo), grepo, strepo


async def test_assign_by_email_matched_deduped_and_unmatched() -> None:
    students = [
        make_student(id="s1", school_id=_S1, user_id="u1", email="ann@x.io"),
        make_student(id="s2", school_id=_S1, user_id="u2", email="bob@x.io"),
    ]
    svc, _, strepo = _class_svc(
        groups=[make_student_group(id="cls-1", school_id=_S1)], students=students
    )
    assigned, unmatched = await svc.assign_students_by_email(
        school_id=_S1,
        group_id="cls-1",
        # case-insensitive match + a duplicate (deduped) + a blank + an unknown email.
        emails=["ann@x.io", "BOB@x.io", "  ", "ghost@x.io", "ann@x.io"],
    )
    assert assigned == 2
    assert unmatched == ["ghost@x.io"]
    s1 = await strepo.get(_S1, "s1")
    s2 = await strepo.get(_S1, "s2")
    assert s1 is not None and s1.student_group_id == "cls-1"
    assert s2 is not None and s2.student_group_id == "cls-1"


async def test_assign_by_email_foreign_class_404() -> None:
    svc, _, _ = _class_svc(groups=[])
    with pytest.raises(NotFoundError):
        await svc.assign_students_by_email(
            school_id=_S1, group_id="ghost", emails=["a@x.io"]
        )


async def test_assign_by_email_foreign_school_email_is_unmatched() -> None:
    """A student in ANOTHER school is never resolved/assigned — reported unmatched (no leak)."""
    s2 = "s2"
    svc, _, strepo = _class_svc(
        groups=[make_student_group(id="cls-1", school_id=_S1)],
        students=[
            make_student(id="s1", school_id=_S1, user_id="u1", email="ours@x.io"),
            make_student(id="sx", school_id=s2, user_id="ux", email="theirs@x.io"),
        ],
    )
    assigned, unmatched = await svc.assign_students_by_email(
        school_id=_S1, group_id="cls-1", emails=["ours@x.io", "theirs@x.io"]
    )
    assert assigned == 1  # only our own student
    assert unmatched == ["theirs@x.io"]  # the foreign-school email never resolves
    foreign = await strepo.get(s2, "sx")
    assert foreign is not None and foreign.student_group_id is None  # not moved into our class


# ======================================================================
# slice 3a · the best-effort class-assign never loses a created student
# ======================================================================


async def test_bulk_import_class_assign_failure_keeps_student_created() -> None:
    """A class create/assign blip must NOT discard the (already-created) student — it stays
    ``created`` (un-classed), best-effort (student_service.py logs + continues)."""

    async def _boom(**_kwargs: object) -> StudentGroup:
        raise RuntimeError("class create boom")

    grepo = FakeStudentGroupRepo()
    grepo.create = _boom  # simulate a class-create outage
    svc, strepo = _student_svc(groups=grepo)
    results = await svc.bulk_create_students(
        school_id=_S1, rows=[("Ann", "ann@x.io", "Grade 3B")]
    )
    assert results[0].status == "created"  # the student survived the class failure
    students = await strepo.list_by_school(_S1)
    assert len(students) == 1 and students[0].student_group_id is None  # un-classed


# ======================================================================
# route smoke — the model_fields_set tri-state (the critical end-to-end contract)
# ======================================================================


def _u(*, id: str, role: Role, email: str) -> User:
    user: User = make_user(
        id=id, school_id=_S1, email=email, password_hash=_HASHER.hash("pw"), role=role
    )
    return user


def _client() -> TestClient:
    events = FakeEventRepo(
        [
            make_event(
                id="e1", school_id=_S1,
                category_id="cat-1", category_name="Sports",
                term="Fall 2026",
                student_group_id="cls-1", student_group_name="Grade 3B",
            )
        ]
    )
    container = SeededContainer(
        FakeUserRepo([_u(id="sa", role=Role.SCHOOL_ADMIN, email="sa@x.io")]),
        FakeSchoolRepo([make_school(id=_S1)]),
        events=events,
        event_categories=FakeEventCategoryRepo(
            [
                make_event_category(id="cat-1", school_id=_S1, name="Sports"),
                make_event_category(id="cat-2", school_id=_S1, name="Arts"),
            ]
        ),
        student_groups=FakeStudentGroupRepo(
            [make_student_group(id="cls-1", school_id=_S1, name="Grade 3B")]
        ),
    )
    app = create_app()
    app.dependency_overrides[get_container_dep] = lambda: container
    return TestClient(app)


def _token(client: TestClient) -> dict[str, str]:
    resp = client.post("/v1/auth/login", json={"email": "sa@x.io", "password": "pw"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_event_patch_tri_state_clears_leaves_and_sets() -> None:
    client = _client()
    auth = _token(client)

    # An empty PATCH leaves the tags unchanged (omitted → UNSET).
    r = client.patch("/v1/events/e1", json={"name": "Renamed"}, headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Renamed"
    assert body["category_id"] == "cat-1" and body["term"] == "Fall 2026"

    # An explicit null clears (present in the body → passed through as None).
    r = client.patch("/v1/events/e1", json={"category_id": None}, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["category_id"] is None and r.json()["category_name"] is None

    # A value sets; the still-present term is untouched.
    r = client.patch("/v1/events/e1", json={"category_id": "cat-2"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["category_id"] == "cat-2" and r.json()["category_name"] == "Arts"

    # Clear the class + the term too.
    r = client.patch(
        "/v1/events/e1", json={"student_group_id": None, "term": None}, headers=auth
    )
    assert r.status_code == 200
    assert r.json()["student_group_id"] is None and r.json()["term"] is None

    # A foreign category is still a 404.
    assert (
        client.patch("/v1/events/e1", json={"category_id": "ghost"}, headers=auth)
    ).status_code == 404


def test_assign_by_email_route_shape() -> None:
    client = _client()
    auth = _token(client)
    # cls-1 exists but has no students → all unmatched (no seeded students in this fixture).
    r = client.post(
        "/v1/classes/cls-1/members/by-email",
        json={"emails": ["nobody@x.io"]},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"assigned": 0, "unmatched": ["nobody@x.io"]}
    # A foreign class → 404.
    assert (
        client.post(
            "/v1/classes/ghost/members/by-email",
            json={"emails": ["a@x.io"]},
            headers=auth,
        )
    ).status_code == 404
