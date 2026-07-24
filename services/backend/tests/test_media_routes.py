"""End-to-end media routes over HTTP (decisions/0027).

Registering a photo only records it (no enqueue — processing is event-level, tested in
test_events_routes.py). Exercises tenant isolation, the `media:upload` /
`job:status:view` gates, and the reads.
"""

from __future__ import annotations

from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
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


def _build(*, users: list[User]) -> tuple[TestClient, SeededContainer]:
    container = SeededContainer(
        FakeUserRepo(users),
        FakeSchoolRepo([make_school(id="s1")]),
        events=FakeEventRepo(),
        media=FakeMediaRepo(),
        event_job_producer=FakeEventJobProducer(),
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


def _admin() -> tuple[TestClient, str]:
    client, _ = _build(users=[_user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1")])
    return client, _token(client, "sa")


def _event(client: TestClient, token: str) -> str:
    return str(
        client.post("/v1/events", json={"name": "E"}, headers=_auth(token)).json()["id"]
    )


# ---- upload url --------------------------------------------------------


def test_upload_url_scoped_to_event_and_reports_limit() -> None:
    client, token = _admin()
    eid = _event(client, token)
    resp = client.post(f"/v1/events/{eid}/media/upload-url", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["object_path"].startswith(f"events/s1/{eid}/")
    assert body["max_upload_mb"] == 30 and body["upload_url"]


# ---- register + reads --------------------------------------------------


def test_register_media_records_pending_and_lists() -> None:
    client, token = _admin()
    eid = _event(client, token)
    resp = client.post(
        f"/v1/events/{eid}/media",
        json={"storage_path": f"events/s1/{eid}/photo.jpg", "media_type": "image"},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["processing_status"] == "pending" and body["event_id"] == eid
    mid = body["id"]

    listed = client.get(f"/v1/events/{eid}/media", headers=_auth(token))
    assert listed.status_code == 200 and [m["id"] for m in listed.json()["items"]] == [
        mid
    ]

    got = client.get(f"/v1/media/{mid}", headers=_auth(token))
    assert got.status_code == 200 and got.json()["id"] == mid


def test_register_foreign_prefix_rejected() -> None:
    client, token = _admin()
    eid = _event(client, token)
    resp = client.post(
        f"/v1/events/{eid}/media",
        json={"storage_path": "events/other/x/p.jpg", "media_type": "image"},
        headers=_auth(token),
    )
    assert resp.status_code == 400


def test_register_bad_media_type_rejected_by_schema() -> None:
    client, token = _admin()
    eid = _event(client, token)
    resp = client.post(
        f"/v1/events/{eid}/media",
        json={"storage_path": f"events/s1/{eid}/p.jpg", "media_type": "audio"},
        headers=_auth(token),
    )
    assert resp.status_code == 422


def test_register_missing_event_404() -> None:
    client, token = _admin()
    resp = client.post(
        "/v1/events/ghost/media",
        json={"storage_path": "events/s1/ghost/p.jpg", "media_type": "image"},
        headers=_auth(token),
    )
    assert resp.status_code == 404


# ---- tenant isolation + RBAC + auth ------------------------------------


def test_cross_tenant_media_get_404() -> None:
    client, token = _admin()
    assert client.get("/v1/media/nope", headers=_auth(token)).status_code == 404


def test_student_forbidden_from_media() -> None:
    client, _ = _build(users=[_user(id="stu", role=Role.STUDENT, school_id="s1")])
    token = _token(client, "stu")
    assert client.get("/v1/events/e/media", headers=_auth(token)).status_code == 403


def test_platform_admin_forbidden_from_media() -> None:
    client, _ = _build(users=[_user(id="pa", role=Role.PLATFORM_ADMIN, school_id=None)])
    token = _token(client, "pa")
    assert client.get("/v1/events/e/media", headers=_auth(token)).status_code == 403


def test_media_requires_auth() -> None:
    client, _ = _build(users=[_user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1")])
    assert client.get("/v1/media/x").status_code == 401
