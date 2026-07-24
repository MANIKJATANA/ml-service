"""End-to-end BP2 list-enrichment routes (decisions/0039).

Asserts the enriched list responses carry their counts and that the platform schools
rollups + admin roster work, gated + tenant-scoped like the rest.
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


def _user(*, id: str, role: Role, school_id: str | None, email: str) -> User:
    user: User = make_user(
        id=id, school_id=school_id, email=email,
        password_hash=_HASHER.hash("pw"), role=role,
    )
    return user


def _build() -> TestClient:
    container = SeededContainer(
        FakeUserRepo(
            [
                _user(id="pa", role=Role.PLATFORM_ADMIN, school_id=None, email="pa@x.io"),
                _user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1", email="sa@x.io"),
                _user(id="te", role=Role.TEACHER, school_id="s1", email="te@x.io"),
            ]
        ),
        FakeSchoolRepo([make_school(id="s1", name="Springfield", max_teachers=10)]),
        students=FakeStudentRepo(
            [make_student(id="st1", school_id="s1", user_id="su", name="Bart")]
        ),
        events=FakeEventRepo([make_event(id="e1", school_id="s1", name="Sports Day")]),
        media=FakeMediaRepo(
            [
                make_media(id="m1", school_id="s1", event_id="e1"),
                make_media(id="m2", school_id="s1", event_id="e1"),
            ]
        ),
        ml_results_reader=FakeMlResultsReader(
            [
                make_appearance(student_id="st1", media_id="m1", event_id="e1"),
                make_appearance(student_id="st1", media_id="m2", event_id="e1",
                                needs_review=True),
            ]
        ),
    )
    app = create_app()
    app.dependency_overrides[get_container_dep] = lambda: container
    return TestClient(app)


def _token(client: TestClient, who: str) -> str:
    resp = client.post("/v1/auth/login", json={"email": f"{who}@x.io", "password": "pw"})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def _auth(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


def test_events_list_carries_counts() -> None:
    client = _build()
    resp = client.get("/v1/events", headers=_auth(_token(client, "sa")))
    assert resp.status_code == 200, resp.text
    page = resp.json()
    assert page["total"] == 1
    row = next(r for r in page["items"] if r["id"] == "e1")
    assert row["media_count"] == 2
    assert row["matched_students"] == 1  # only st1 matched
    assert row["needs_review"] == 1


def test_students_list_carries_counts() -> None:
    client = _build()
    resp = client.get("/v1/students", headers=_auth(_token(client, "sa")))
    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json()["items"] if r["id"] == "st1")
    assert row["appearance_count"] == 2  # in m1 + m2
    assert row["event_count"] == 1
    assert row["email"] == "student@example.com"  # F3 additive still present


def test_schools_list_carries_rollup() -> None:
    client = _build()
    resp = client.get("/v1/schools", headers=_auth(_token(client, "pa")))
    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json()["items"] if r["id"] == "s1")
    assert row["max_teachers"] == 10
    assert row["rollup"] == {"admins": 1, "teachers": 1, "students": 1, "events": 1}


def test_school_detail_carries_rollup() -> None:
    client = _build()
    resp = client.get("/v1/schools/s1", headers=_auth(_token(client, "pa")))
    assert resp.status_code == 200, resp.text
    assert resp.json()["rollup"]["teachers"] == 1


def test_school_admin_roster() -> None:
    client = _build()
    resp = client.get("/v1/schools/s1/admins", headers=_auth(_token(client, "pa")))
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    emails = {u["email"] for u in items}
    assert emails == {"sa@x.io"}  # only the school_admin, not the teacher
    assert "created_at" in items[0]  # BP2 additive field


def test_schools_and_roster_are_platform_only() -> None:
    client = _build()
    # A school_admin lacks school:manage -> 403 on the platform routes.
    assert client.get("/v1/schools", headers=_auth(_token(client, "sa"))).status_code == 403
    assert (
        client.get("/v1/schools/s1/admins", headers=_auth(_token(client, "sa"))).status_code
        == 403
    )
