"""End-to-end student "this isn't me" (BP5, decisions/0042).

A student self-rejects a wrongly-matched photo: it leaves their gallery + blocks their
download. Guards: 404 if they don't currently appear; staff can't use the /me route.
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
    # st1 (login stu) appears in m1 only; m2 exists but st1 isn't in it.
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
        events=FakeEventRepo([make_event(id="e1", school_id="s1")]),
        media=FakeMediaRepo(
            [
                make_media(id="m1", school_id="s1", event_id="e1"),
                make_media(id="m2", school_id="s1", event_id="e1"),
            ]
        ),
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


def _auth(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


def test_not_me_removes_photo_and_blocks_download() -> None:
    client = _build()
    stu = _auth(_token(client, "stu"))

    # Before: st1 sees m1 and can download it.
    assert [m["media_id"] for m in client.get("/v1/me/media", headers=stu).json()] == ["m1"]
    assert client.get("/v1/media/m1/download", headers=stu).status_code == 200

    # "This isn't me" on m1.
    resp = client.post("/v1/me/media/m1/not-me", headers=stu)
    assert resp.status_code == 204, resp.text

    # After: m1 is gone from their gallery and the download is blocked (404).
    assert client.get("/v1/me/media", headers=stu).json() == []
    assert client.get("/v1/media/m1/download", headers=stu).status_code == 404


def test_not_me_on_a_photo_they_dont_appear_in_is_404() -> None:
    client = _build()
    stu = _auth(_token(client, "stu"))
    # st1 isn't in m2 -> 404 (never confirms a photo they can't see).
    assert client.post("/v1/me/media/m2/not-me", headers=stu).status_code == 404


def test_not_me_is_student_only() -> None:
    client = _build()
    sa = _auth(_token(client, "sa"))  # staff lack gallery:view_own
    assert client.post("/v1/me/media/m1/not-me", headers=sa).status_code == 403
    assert client.post("/v1/me/media/m1/not-me").status_code == 401
