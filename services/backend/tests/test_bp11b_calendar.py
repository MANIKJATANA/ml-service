"""BP11b — event term/category + calendar filters (decisions/0059).

Service-level category lifecycle (add/dedupe/delete-un-tags/seed) + event create/update with
category+term (foreign category → 404, term clean/can't-clear), then the routes: the
``event:manage`` category CRUD (list/add-409/delete-404), the events list category/term/
date-range filters (incl. the count-sort path), the terms endpoint, seed-on-school-create,
and auth.
"""

from __future__ import annotations

from datetime import date

import pytest
from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.domain.errors import ConflictError, NotFoundError
from backend.domain.models import Event, EventCategory, Role, School, User
from backend.main import create_app
from backend.services.event_category_service import EventCategoryService
from backend.services.event_service import EventService
from backend.services.onboarding_service import OnboardingService
from backend_fakes import (
    FakeAdminActionAuditRepo,
    FakeEventCategoryRepo,
    FakeEventJobProducer,
    FakeEventRepo,
    FakeHasher,
    FakeMediaRepo,
    FakeSchoolRepo,
    FakeStudentGroupRepo,
    FakeUserRepo,
    SeededContainer,
    make_event,
    make_event_category,
    make_school,
    make_user,
)
from fastapi.testclient import TestClient

_S1 = "s1"
_S2 = "s2"


# ---- service helpers --------------------------------------------------


def _wire(
    categories: list[EventCategory] | None, events: list[Event] | None
) -> tuple[FakeEventCategoryRepo, FakeEventRepo]:
    crepo = FakeEventCategoryRepo(categories or [])
    erepo = FakeEventRepo(events or [])
    erepo.link_categories(crepo.name_of)
    crepo.link_events(erepo.untag_category)
    return crepo, erepo


def _event_svc(
    *, events: list[Event] | None = None, categories: list[EventCategory] | None = None
) -> tuple[EventService, FakeEventRepo, FakeEventCategoryRepo]:
    crepo, erepo = _wire(categories, events)
    svc = EventService(
        erepo,
        FakeMediaRepo(),
        FakeEventJobProducer(),
        crepo,
        FakeStudentGroupRepo(),
        FakeUserRepo(),
    )
    return svc, erepo, crepo


def _cat_svc(
    *, categories: list[EventCategory] | None = None, events: list[Event] | None = None
) -> tuple[EventCategoryService, FakeEventCategoryRepo, FakeEventRepo]:
    crepo, erepo = _wire(categories, events)
    return EventCategoryService(crepo), crepo, erepo


# ---- service: events with category + term -----------------------------


async def test_create_event_with_category_and_term_carries_the_name() -> None:
    svc, _, _ = _event_svc(
        categories=[make_event_category(id="c1", school_id=_S1, name="Sports")]
    )
    event = await svc.create_event(
        school_id=_S1,
        name="Sports Day",
        description=None,
        event_date=date(2026, 7, 4),
        created_by="u1",
        category_id="c1",
        term="  Fall 2026  ",
    )
    assert event.category_id == "c1"
    assert event.category_name == "Sports"
    assert event.term == "Fall 2026"  # trimmed


async def test_create_event_foreign_category_is_404() -> None:
    # A category from another school can never be tagged (no cross-tenant).
    svc, _, _ = _event_svc(
        categories=[make_event_category(id="c1", school_id=_S2, name="Sports")]
    )
    with pytest.raises(NotFoundError):
        await svc.create_event(
            school_id=_S1,
            name="X",
            description=None,
            event_date=None,
            created_by="u1",
            category_id="c1",
        )


async def test_create_event_empty_term_is_stored_as_none() -> None:
    svc, _, _ = _event_svc()
    event = await svc.create_event(
        school_id=_S1,
        name="X",
        description=None,
        event_date=None,
        created_by="u1",
        term="   ",
    )
    assert event.term is None


async def test_update_event_changes_category_and_term() -> None:
    svc, _, _ = _event_svc(
        categories=[make_event_category(id="c1", school_id=_S1, name="Arts")],
        events=[make_event(id="e1", school_id=_S1)],
    )
    updated = await svc.update_event(
        school_id=_S1, event_id="e1", category_id="c1", term="Term 1"
    )
    assert updated.category_id == "c1" and updated.category_name == "Arts"
    assert updated.term == "Term 1"


async def test_update_empty_term_clears_it_but_omitted_leaves_it() -> None:
    # BP24 (decisions/0079) revises BP11b/0027: an explicit empty/whitespace term now CLEARS it
    # (a provided field is set/cleared), while OMITTING term leaves it unchanged.
    svc, _, _ = _event_svc(events=[make_event(id="e1", school_id=_S1, term="Fall")])
    cleared = await svc.update_event(school_id=_S1, event_id="e1", term="   ")
    assert cleared.term is None  # explicitly emptied → cleared
    svc2, _, _ = _event_svc(events=[make_event(id="e2", school_id=_S1, term="Spring")])
    unchanged = await svc2.update_event(school_id=_S1, event_id="e2", name="x")
    assert unchanged.term == "Spring"  # omitted → unchanged (UNSET)


async def test_list_terms_is_distinct_and_sorted() -> None:
    svc, _, _ = _event_svc(
        events=[
            make_event(id="e1", school_id=_S1, term="Spring"),
            make_event(id="e2", school_id=_S1, term="Fall"),
            make_event(id="e3", school_id=_S1, term="Fall"),
            make_event(id="e4", school_id=_S1, term=None),
            make_event(id="e5", school_id=_S2, term="Winter"),  # other school
        ]
    )
    assert await svc.list_terms(school_id=_S1) == ["Fall", "Spring"]


# ---- service: category lifecycle --------------------------------------


async def test_add_category_dedupes_case_insensitively() -> None:
    svc, _, _ = _cat_svc(
        categories=[make_event_category(id="c1", school_id=_S1, name="Sports")]
    )
    with pytest.raises(ConflictError):
        await svc.add_category(school_id=_S1, name="  sports  ")


async def test_delete_category_untags_its_events() -> None:
    svc, _, erepo = _cat_svc(
        categories=[make_event_category(id="c1", school_id=_S1, name="Sports")],
        events=[make_event(id="e1", school_id=_S1, category_id="c1")],
    )
    await svc.delete_category(school_id=_S1, category_id="c1")
    left = await erepo.get(_S1, "e1")
    assert left is not None and left.category_id is None  # SET NULL, event kept


async def test_delete_foreign_category_is_404() -> None:
    svc, _, _ = _cat_svc(
        categories=[make_event_category(id="c1", school_id=_S1, name="Sports")]
    )
    with pytest.raises(NotFoundError):
        await svc.delete_category(school_id=_S2, category_id="c1")


async def test_create_school_seeds_the_default_categories() -> None:
    crepo = FakeEventCategoryRepo()
    onboarding = OnboardingService(
        FakeSchoolRepo(), FakeUserRepo(), FakeHasher(), crepo, FakeAdminActionAuditRepo()
    )
    school = await onboarding.create_school(name="New School", max_teachers=5)
    names = sorted(c.name for c in await crepo.list_by_school(school.id))
    assert names == ["Academic", "Arts", "Ceremony", "Other", "Sports", "Trip"]


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
    events: FakeEventRepo | None = None,
    categories: FakeEventCategoryRepo | None = None,
) -> tuple[TestClient, SeededContainer]:
    container = SeededContainer(
        FakeUserRepo(users),
        FakeSchoolRepo(schools if schools is not None else [make_school(id=_S1)]),
        events=events or FakeEventRepo(),
        event_categories=categories or FakeEventCategoryRepo(),
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
    events: FakeEventRepo | None = None,
    categories: FakeEventCategoryRepo | None = None,
) -> tuple[TestClient, str]:
    client, _ = _build(
        users=[_user(id="sa", role=Role.SCHOOL_ADMIN, school_id=_S1)],
        events=events,
        categories=categories,
    )
    return client, _token(client, "sa")


def test_list_and_add_categories() -> None:
    cats = FakeEventCategoryRepo([make_event_category(id="c1", school_id=_S1, name="Sports")])
    client, token = _admin_client(categories=cats)
    listed = client.get("/v1/event-categories", headers=_auth(token))
    assert listed.status_code == 200
    assert [c["name"] for c in listed.json()] == ["Sports"]

    created = client.post(
        "/v1/event-categories", json={"name": "Chess Club"}, headers=_auth(token)
    )
    assert created.status_code == 201, created.text
    assert created.json()["name"] == "Chess Club"


def test_add_duplicate_category_is_409() -> None:
    cats = FakeEventCategoryRepo([make_event_category(id="c1", school_id=_S1, name="Sports")])
    client, token = _admin_client(categories=cats)
    resp = client.post(
        "/v1/event-categories", json={"name": "sports"}, headers=_auth(token)
    )
    assert resp.status_code == 409


def test_category_write_requires_event_manage() -> None:
    client, _ = _build(users=[_user(id="stu", role=Role.STUDENT, school_id=_S1)])
    token = _token(client, "stu")
    assert (
        client.post(
            "/v1/event-categories", json={"name": "X"}, headers=_auth(token)
        ).status_code
        == 403
    )


def test_teacher_can_manage_categories() -> None:
    # Categories are admins + staff (event:manage) — a teacher CAN add (unlike class:manage).
    client, _ = _build(users=[_user(id="te", role=Role.TEACHER, school_id=_S1)])
    token = _token(client, "te")
    resp = client.post(
        "/v1/event-categories", json={"name": "Assembly"}, headers=_auth(token)
    )
    assert resp.status_code == 201


def test_delete_category_204_and_foreign_404() -> None:
    cats = FakeEventCategoryRepo([make_event_category(id="c1", school_id=_S1, name="Sports")])
    client, token = _admin_client(categories=cats)
    assert (
        client.delete("/v1/event-categories/c1", headers=_auth(token)).status_code == 204
    )
    # Now gone → 404.
    assert (
        client.delete("/v1/event-categories/c1", headers=_auth(token)).status_code == 404
    )


def test_create_event_with_category_and_term_via_route() -> None:
    cats = FakeEventCategoryRepo([make_event_category(id="c1", school_id=_S1, name="Sports")])
    client, token = _admin_client(categories=cats)
    resp = client.post(
        "/v1/events",
        json={"name": "Sports Day", "category_id": "c1", "term": "Fall 2026"},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["category_id"] == "c1" and body["category_name"] == "Sports"
    assert body["term"] == "Fall 2026"


def test_events_filter_by_category_and_term() -> None:
    events = FakeEventRepo(
        [
            make_event(id="e1", school_id=_S1, name="A", category_id="c1", term="Fall"),
            make_event(id="e2", school_id=_S1, name="B", category_id="c2", term="Fall"),
            make_event(id="e3", school_id=_S1, name="C", category_id="c1", term="Spring"),
        ]
    )
    client, token = _admin_client(events=events)
    by_cat = client.get(
        "/v1/events", params={"category_id": "c1"}, headers=_auth(token)
    )
    assert {x["id"] for x in by_cat.json()["items"]} == {"e1", "e3"}
    by_both = client.get(
        "/v1/events",
        params={"category_id": "c1", "term": "Fall"},
        headers=_auth(token),
    )
    assert [x["id"] for x in by_both.json()["items"]] == ["e1"]


def test_events_filter_by_date_range_excludes_undated() -> None:
    events = FakeEventRepo(
        [
            make_event(id="e1", school_id=_S1, name="A", event_date=date(2026, 7, 4)),
            make_event(id="e2", school_id=_S1, name="B", event_date=date(2026, 7, 20)),
            make_event(id="e3", school_id=_S1, name="C", event_date=date(2026, 8, 2)),
            make_event(id="e4", school_id=_S1, name="D", event_date=None),  # undated
        ]
    )
    client, token = _admin_client(events=events)
    resp = client.get(
        "/v1/events",
        params={"date_from": "2026-07-01", "date_to": "2026-07-31"},
        headers=_auth(token),
    )
    ids = {x["id"] for x in resp.json()["items"]}
    assert ids == {"e1", "e2"}  # e3 out of range, e4 undated (excluded)


def test_events_category_filter_threads_through_count_sort() -> None:
    events = FakeEventRepo(
        [
            make_event(id="e1", school_id=_S1, name="A", category_id="c1"),
            make_event(id="e2", school_id=_S1, name="B", category_id="c1"),
            make_event(id="e3", school_id=_S1, name="C", category_id="c2"),
        ]
    )
    client, token = _admin_client(events=events)
    resp = client.get(
        "/v1/events",
        params={"category_id": "c1", "sort": "media_count", "dir": "desc"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert {x["id"] for x in resp.json()["items"]} == {"e1", "e2"}


def test_get_events_terms() -> None:
    events = FakeEventRepo(
        [
            make_event(id="e1", school_id=_S1, term="Spring"),
            make_event(id="e2", school_id=_S1, term="Fall"),
            make_event(id="e3", school_id=_S1, term=None),
        ]
    )
    client, token = _admin_client(events=events)
    resp = client.get("/v1/events/terms", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["terms"] == ["Fall", "Spring"]


def test_create_event_with_a_bad_category_is_404_via_route() -> None:
    client, token = _admin_client()  # no categories seeded
    resp = client.post(
        "/v1/events",
        json={"name": "X", "category_id": "nope"},
        headers=_auth(token),
    )
    assert resp.status_code == 404


def test_update_event_category_and_term_via_route() -> None:
    # Guards the PATCH wiring (router → update_event → response carrying category_name).
    cats = FakeEventCategoryRepo([make_event_category(id="c1", school_id=_S1, name="Arts")])
    events = FakeEventRepo([make_event(id="e1", school_id=_S1)])
    client, token = _admin_client(events=events, categories=cats)
    resp = client.patch(
        "/v1/events/e1",
        json={"category_id": "c1", "term": "Term 1"},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["category_id"] == "c1" and body["category_name"] == "Arts"
    assert body["term"] == "Term 1"


def test_events_filter_by_date_from_only() -> None:
    # The API allows an open-ended range (the calendar always sends both, but one is valid).
    events = FakeEventRepo(
        [
            make_event(id="e1", school_id=_S1, name="A", event_date=date(2026, 7, 4)),
            make_event(id="e2", school_id=_S1, name="B", event_date=date(2026, 7, 20)),
            make_event(id="e3", school_id=_S1, name="C", event_date=None),
        ]
    )
    client, token = _admin_client(events=events)
    resp = client.get("/v1/events", params={"date_from": "2026-07-15"}, headers=_auth(token))
    assert {x["id"] for x in resp.json()["items"]} == {"e2"}  # on/after only; undated excluded


def test_add_category_rejects_blank_and_over_length() -> None:
    client, token = _admin_client()
    # "" fails the schema min_length=1 → 422; "   " passes it but the service strip-guard → 400.
    assert (
        client.post("/v1/event-categories", json={"name": ""}, headers=_auth(token)).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/event-categories", json={"name": "   "}, headers=_auth(token)
        ).status_code
        == 400
    )
    over = client.post(
        "/v1/event-categories", json={"name": "x" * 61}, headers=_auth(token)
    )
    assert over.status_code == 422
    at_cap = client.post(
        "/v1/event-categories", json={"name": "y" * 60}, headers=_auth(token)
    )
    assert at_cap.status_code == 201


def test_teacher_can_delete_a_category() -> None:
    # Category management is event:manage (admins + staff) — a teacher can delete too.
    cats = FakeEventCategoryRepo([make_event_category(id="c1", school_id=_S1, name="Sports")])
    client, _ = _build(
        users=[_user(id="te", role=Role.TEACHER, school_id=_S1)], categories=cats
    )
    token = _token(client, "te")
    assert client.delete("/v1/event-categories/c1", headers=_auth(token)).status_code == 204


def test_event_category_routes_require_auth() -> None:
    client, _ = _build(users=[_user(id="sa", role=Role.SCHOOL_ADMIN, school_id=_S1)])
    assert client.get("/v1/event-categories").status_code == 401
    assert client.post("/v1/event-categories", json={"name": "X"}).status_code == 401
    assert client.get("/v1/events/terms").status_code == 401
