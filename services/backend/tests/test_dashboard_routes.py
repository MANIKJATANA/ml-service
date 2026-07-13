"""End-to-end dashboard route over HTTP (BP1, decisions/0038).

`GET /v1/dashboard` returns the caller's own school rollup; gated on `dashboard:view`
(school_admin + teacher, not student), tenant always from the token.
"""

from __future__ import annotations

from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.domain.models import (
    EnrollmentStatus,
    EventProcessingStatus,
    MediaProcessingStatus,
    Role,
    User,
)
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
    """School s1: an admin, a teacher, and a student login; 1 enrolled student, one
    not_started event with a pending photo (an undistributed alert), one needs_review
    match. Plus a school-s2 admin for cross-tenant isolation."""
    container = SeededContainer(
        FakeUserRepo(
            [
                _user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1"),
                _user(id="te", role=Role.TEACHER, school_id="s1"),
                _user(id="stu", role=Role.STUDENT, school_id="s1"),
                _user(id="sa2", role=Role.SCHOOL_ADMIN, school_id="s2"),
            ]
        ),
        FakeSchoolRepo([make_school(id="s1", name="Springfield"), make_school(id="s2")]),
        students=FakeStudentRepo(
            [
                make_student(id="st1", school_id="s1", user_id="stu",
                             enrollment_status=EnrollmentStatus.ENROLLED),
            ]
        ),
        events=FakeEventRepo(
            [
                make_event(id="e1", school_id="s1",
                           processing_status=EventProcessingStatus.NOT_STARTED),
            ]
        ),
        media=FakeMediaRepo(
            [
                make_media(id="m1", school_id="s1", event_id="e1",
                           processing_status=MediaProcessingStatus.PENDING),
            ]
        ),
        ml_results_reader=FakeMlResultsReader(
            [make_appearance(student_id="st1", media_id="m1", event_id="e1",
                             needs_review=True)]
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


def test_admin_gets_own_school_rollup() -> None:
    client = _build()
    resp = client.get("/v1/dashboard", headers=_auth(_token(client, "sa")))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["school_name"] == "Springfield"
    assert body["students"] == {"total": 1, "enrolled": 1, "pending": 0, "failed": 0}
    assert body["events"]["total"] == 1
    assert body["media"] == {"total": 1, "pending": 1}
    assert body["needs_attention"] == {
        "events_undistributed": 1,
        "enrollment_failures": 0,
        "needs_review": 1,
    }


def test_teacher_may_view_dashboard() -> None:
    client = _build()
    resp = client.get("/v1/dashboard", headers=_auth(_token(client, "te")))
    assert resp.status_code == 200, resp.text


def test_student_is_forbidden() -> None:
    client = _build()
    resp = client.get("/v1/dashboard", headers=_auth(_token(client, "stu")))
    assert resp.status_code == 403


def test_requires_authentication() -> None:
    client = _build()
    assert client.get("/v1/dashboard").status_code == 401


def test_tenant_is_from_the_token_other_school_sees_its_own() -> None:
    # The s2 admin's school has no students/events/photos — never s1's numbers. The
    # repo-backed counts are tenant-scoped by the fakes; the reader's needs_review scope
    # is an adapter-SQL guarantee (WHERE school_id=...), which the school-agnostic
    # FakeMlResultsReader can't model (Appearance carries no school_id), so it isn't
    # asserted here.
    client = _build()
    resp = client.get("/v1/dashboard", headers=_auth(_token(client, "sa2")))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["students"]["total"] == 0
    assert body["events"]["total"] == 0
    assert body["media"]["total"] == 0
    assert body["needs_attention"]["events_undistributed"] == 0
