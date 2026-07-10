"""Student self-scoped `/me` gallery routes over HTTP (decisions/0028).

A logged-in student sees only the events/photos they appear in; their student_id is
resolved from the token, never supplied. Staff (no `gallery:view_own`) and a student
login without a profile are refused.
"""

from __future__ import annotations

from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.domain.models import Role, User
from backend.main import create_app
from backend_fakes import (
    FakeEventRepo,
    FakeMediaRepo,
    FakeMlResultsReader,
    FakeSchoolRepo,
    FakeStudentRepo,
    FakeUserRepo,
    SeededContainer,
    make_appearance,
    make_event,
    make_media,
    make_school,
    make_student,
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


def _build() -> TestClient:
    """s1: a student login (stu→st1) in e1/m1, an admin, and an orphan student login
    (no profile)."""
    container = SeededContainer(
        FakeUserRepo(
            [
                _user(id="stu", role=Role.STUDENT, school_id="s1"),
                _user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1"),
                _user(id="orphan", role=Role.STUDENT, school_id="s1"),
                # A student with a profile but who appears in nothing yet.
                _user(id="stu2", role=Role.STUDENT, school_id="s1"),
            ]
        ),
        FakeSchoolRepo([make_school(id="s1")]),
        students=FakeStudentRepo(
            [
                make_student(id="st1", school_id="s1", user_id="stu", name="Bart"),
                make_student(id="st2", school_id="s1", user_id="stu2", name="Lisa"),
            ]
        ),
        events=FakeEventRepo([make_event(id="e1", school_id="s1")]),
        media=FakeMediaRepo([make_media(id="m1", school_id="s1", event_id="e1")]),
        ml_results_reader=FakeMlResultsReader(
            [make_appearance(student_id="st1", media_id="m1", event_id="e1")]
        ),
    )
    app = create_app()
    app.dependency_overrides[get_container_dep] = lambda: container
    return TestClient(app)


def _token(client: TestClient, who: str) -> str:
    resp = client.post("/v1/auth/login", json={"email": f"{who}@x.io", "password": "pw"})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_me_events_and_media() -> None:
    client = _build()
    token = _token(client, "stu")

    events = client.get("/v1/me/events", headers=_auth(token))
    assert events.status_code == 200, events.text
    assert [e["event_id"] for e in events.json()] == ["e1"]

    media = client.get("/v1/me/media", headers=_auth(token))
    assert [m["media_id"] for m in media.json()] == ["m1"]

    filtered = client.get(
        "/v1/me/media", params={"event_id": "e1"}, headers=_auth(token)
    )
    assert [m["media_id"] for m in filtered.json()] == ["m1"]

    # Filtering to an event the student isn't in / doesn't exist -> 404 (guarded).
    foreign = client.get(
        "/v1/me/media", params={"event_id": "ghost"}, headers=_auth(token)
    )
    assert foreign.status_code == 404


def test_me_student_with_profile_but_no_appearances_gets_empty_ok() -> None:
    # The quiet-success path: a real student who appears in nothing sees 200 [] (not 404).
    client = _build()
    token = _token(client, "stu2")
    events = client.get("/v1/me/events", headers=_auth(token))
    assert events.status_code == 200 and events.json() == []
    media = client.get("/v1/me/media", headers=_auth(token))
    assert media.status_code == 200 and media.json() == []


def test_me_forbidden_for_staff() -> None:
    client = _build()
    token = _token(client, "sa")  # school_admin has view_all, not view_own
    assert client.get("/v1/me/events", headers=_auth(token)).status_code == 403


def test_me_forbidden_for_student_without_profile() -> None:
    client = _build()
    token = _token(client, "orphan")
    assert client.get("/v1/me/events", headers=_auth(token)).status_code == 403


def test_me_requires_auth() -> None:
    client = _build()
    assert client.get("/v1/me/events").status_code == 401
