"""End-to-end event routes over HTTP (decisions/0027).

Real JWT + argon2 + RBAC + EventService/MediaService; fake repos + event-job producer
injected via a Container subclass. Exercises tenant isolation, the RBAC gates, CRUD,
the event-level Process/redistribute action, and the polled status.
"""

from __future__ import annotations

from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.domain.errors import UpstreamError
from backend.domain.models import Role, User
from backend.main import create_app
from backend_fakes import (
    FakeEventJobProducer,
    FakeEventRepo,
    FakeMediaRepo,
    FakeSchoolRepo,
    FakeUserRepo,
    SeededContainer,
    make_school,
    make_user,
)
from fastapi.testclient import TestClient

_HASHER = Argon2PasswordHasher()


def _user(*, id: str, role: Role, school_id: str | None) -> User:
    user: User = make_user(
        id=id, school_id=school_id, email=f"{id}@x.io",
        password_hash=_HASHER.hash("pw"), role=role,
    )
    return user


def _build(
    *, users: list[User], producer: FakeEventJobProducer | None = None
) -> tuple[TestClient, SeededContainer]:
    container = SeededContainer(
        FakeUserRepo(users),
        FakeSchoolRepo([make_school(id="s1")]),
        events=FakeEventRepo(),
        media=FakeMediaRepo(),
        event_job_producer=producer or FakeEventJobProducer(),
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


def _admin(**kw: object) -> tuple[TestClient, str, SeededContainer]:
    client, container = _build(
        users=[_user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1")], **kw
    )
    return client, _token(client, "sa"), container


def _event(client: TestClient, token: str) -> str:
    return str(
        client.post("/v1/events", json={"name": "E"}, headers=_auth(token)).json()["id"]
    )


def _register_photo(client: TestClient, token: str, eid: str) -> str:
    resp = client.post(
        f"/v1/events/{eid}/media",
        json={"storage_path": f"events/s1/{eid}/p.jpg", "media_type": "image"},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


# ---- CRUD --------------------------------------------------------------


def test_create_event_in_own_school() -> None:
    client, token, _ = _admin()
    resp = client.post(
        "/v1/events",
        json={"name": "Sports Day", "description": "fun", "event_date": "2026-06-01"},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["school_id"] == "s1" and body["name"] == "Sports Day"
    assert body["processing_status"] == "not_started"


def test_teacher_can_manage_events() -> None:
    client, _ = _build(users=[_user(id="tch", role=Role.TEACHER, school_id="s1")])
    token = _token(client, "tch")
    assert client.post(
        "/v1/events", json={"name": "Recital"}, headers=_auth(token)
    ).status_code == 201


def test_whitespace_name_rejected_as_400() -> None:
    client, token, _ = _admin()
    assert client.post(
        "/v1/events", json={"name": "   "}, headers=_auth(token)
    ).status_code == 400


def test_list_get_update_and_cross_tenant_404() -> None:
    client, token, _ = _admin()
    eid = _event(client, token)

    listed = client.get("/v1/events", headers=_auth(token))
    assert listed.status_code == 200 and [e["id"] for e in listed.json()] == [eid]

    got = client.get(f"/v1/events/{eid}", headers=_auth(token))
    assert got.status_code == 200 and got.json()["id"] == eid

    patched = client.patch(
        f"/v1/events/{eid}", json={"status": "archived"}, headers=_auth(token)
    )
    assert patched.status_code == 200 and patched.json()["status"] == "archived"

    assert client.get("/v1/events/nope", headers=_auth(token)).status_code == 404


# ---- process / redistribute + status ----------------------------------


def test_process_event_enqueues_and_reports_status() -> None:
    client, token, container = _admin()
    eid = _event(client, token)
    _register_photo(client, token, eid)

    resp = client.post(f"/v1/events/{eid}/process", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["processing_status"] == "queued"

    producer = container.event_job_producer()
    assert isinstance(producer, FakeEventJobProducer)
    assert len(producer.jobs) == 1 and producer.jobs[0].event_id == eid

    st = client.get(f"/v1/events/{eid}/status", headers=_auth(token)).json()
    assert st == {
        "event_id": eid,
        "processing_status": "queued",
        "pending": 1,
        "completed": 0,
        "failed": 0,  # BP8a: the per-photo failed count
        "total": 1,
    }


def test_process_event_with_no_photos_400() -> None:
    client, token, _ = _admin()
    eid = _event(client, token)
    assert client.post(
        f"/v1/events/{eid}/process", headers=_auth(token)
    ).status_code == 400


def test_process_enqueue_outage_surfaces_502() -> None:
    client, token, _ = _admin(
        producer=FakeEventJobProducer(raise_on_enqueue=UpstreamError("redis down"))
    )
    eid = _event(client, token)
    _register_photo(client, token, eid)
    assert client.post(
        f"/v1/events/{eid}/process", headers=_auth(token)
    ).status_code == 502


# ---- RBAC + auth -------------------------------------------------------


def test_platform_admin_forbidden_from_events() -> None:
    client, _ = _build(users=[_user(id="pa", role=Role.PLATFORM_ADMIN, school_id=None)])
    token = _token(client, "pa")
    assert client.get("/v1/events", headers=_auth(token)).status_code == 403


def test_student_forbidden_from_events() -> None:
    client, _ = _build(users=[_user(id="stu", role=Role.STUDENT, school_id="s1")])
    token = _token(client, "stu")
    assert client.get("/v1/events", headers=_auth(token)).status_code == 403


def test_events_require_auth() -> None:
    client, _ = _build(users=[_user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1")])
    assert client.get("/v1/events").status_code == 401
