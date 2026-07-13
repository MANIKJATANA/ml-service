"""End-to-end BP4 distribution routes (decisions/0041).

Staff notify + roster (gated on notification:send), and the student /me new-photos signal
+ mark-seen. Tenant + RBAC enforced like the rest.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.domain.models import Role, User
from backend.main import create_app
from backend_fakes import (
    FakeEventRepo,
    FakeMlResultsReader,
    FakeNotificationChannel,
    FakeSchoolRepo,
    FakeStudentRepo,
    FakeUserRepo,
    SeededContainer,
    make_appearance,
    make_event,
    make_school,
    make_student,
    make_user,
)
from fastapi.testclient import TestClient

_HASHER = Argon2PasswordHasher()
# Match backend_fakes._NOW so mark_seen (which stamps _NOW) counts as seen for an event
# completed at this time.
_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _user(*, id: str, role: Role, school_id: str | None, email: str) -> User:
    user: User = make_user(
        id=id, school_id=school_id, email=email,
        password_hash=_HASHER.hash("pw"), role=role,
    )
    return user


def _build() -> tuple[TestClient, FakeNotificationChannel]:
    notifier = FakeNotificationChannel()
    container = SeededContainer(
        FakeUserRepo(
            [
                _user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1", email="sa@x.io"),
                _user(id="stu", role=Role.STUDENT, school_id="s1", email="stu@x.io"),
            ]
        ),
        FakeSchoolRepo([make_school(id="s1")]),
        students=FakeStudentRepo(
            [make_student(id="st1", school_id="s1", user_id="stu", name="Bart")]
        ),
        # An auto event, completed at _NOW (so it is announced to students).
        events=FakeEventRepo(
            [make_event(id="e1", school_id="s1", name="Sports Day", completed_at=_NOW)]
        ),
        ml_results_reader=FakeMlResultsReader(
            [make_appearance(student_id="st1", media_id="m1", event_id="e1")]
        ),
        notifier=notifier,
    )
    app = create_app()
    app.dependency_overrides[get_container_dep] = lambda: container
    return TestClient(app), notifier


def _token(client: TestClient, who: str) -> str:
    resp = client.post("/v1/auth/login", json={"email": f"{who}@x.io", "password": "pw"})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def _auth(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


def test_staff_notify_and_roster() -> None:
    client, notifier = _build()
    sa = _auth(_token(client, "sa"))

    resp = client.post("/v1/events/e1/notify", headers=sa)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"notified": 1}
    assert len(notifier.sent) == 1  # fanned out to the log/fake channel

    roster = client.get("/v1/events/e1/notifications", headers=sa)
    assert roster.status_code == 200, roster.text
    body = roster.json()
    assert body["announced"] is True
    assert body["notified_count"] == 1
    assert [s["student_id"] for s in body["students"]] == ["st1"]


def test_student_sees_new_photos_then_marks_seen() -> None:
    client, _ = _build()
    stu = _auth(_token(client, "stu"))

    got = client.get("/v1/me/notifications", headers=stu)
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["unseen_count"] == 1
    assert body["events"][0]["event_id"] == "e1"
    assert body["events"][0]["unseen"] is True

    seen = client.post("/v1/me/notifications/e1/seen", headers=stu)
    assert seen.status_code == 204, seen.text

    after = client.get("/v1/me/notifications", headers=stu)
    assert after.json()["unseen_count"] == 0


def test_notify_is_staff_only() -> None:
    client, _ = _build()
    stu = _auth(_token(client, "stu"))
    # A student lacks notification:send.
    assert client.post("/v1/events/e1/notify", headers=stu).status_code == 403
    assert client.get("/v1/events/e1/notifications", headers=stu).status_code == 403


def test_notifications_require_auth() -> None:
    client, _ = _build()
    assert client.get("/v1/me/notifications").status_code == 401
    assert client.post("/v1/events/e1/notify").status_code == 401
