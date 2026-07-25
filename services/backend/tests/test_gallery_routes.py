"""End-to-end gallery + download routes over HTTP (decisions/0028).

Staff (`gallery:view_all`) browse the two views + appearances; download is
entitlement-gated (staff any / student own). Exercises tenant isolation, the RBAC gate,
and auth.
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
    """A school (s1) with an admin + a student login (stu→st1), one event, one media
    (m1) the student appears in, plus an event-only media (m2) nobody matched."""
    container = SeededContainer(
        FakeUserRepo(
            [
                _user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1"),
                _user(id="stu", role=Role.STUDENT, school_id="s1"),
                # A school-B admin, for cross-tenant isolation checks.
                _user(id="sa2", role=Role.SCHOOL_ADMIN, school_id="s2"),
            ]
        ),
        FakeSchoolRepo([make_school(id="s1"), make_school(id="s2")]),
        students=FakeStudentRepo(
            [make_student(id="st1", school_id="s1", user_id="stu", name="Bart")]
        ),
        events=FakeEventRepo([make_event(id="e1", school_id="s1", name="Sports Day")]),
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


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _admin() -> tuple[TestClient, str]:
    client = _build()
    return client, _token(client, "sa")


# ---- staff views -------------------------------------------------------


def test_event_students_lists_appearing_with_counts() -> None:
    client, token = _admin()
    resp = client.get("/v1/events/e1/students", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == [{"student_id": "st1", "name": "Bart", "media_count": 1}]


def test_event_student_media_returns_metadata_only() -> None:
    client, token = _admin()
    resp = client.get("/v1/events/e1/students/st1/media", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # BP17: the gallery item carries has_thumbnail (whether a display thumbnail exists) — but
    # never the internal storage/thumbnail *paths* (metadata-only, 0028).
    assert body == [
        {"media_id": "m1", "event_id": "e1", "media_type": "image", "has_thumbnail": False}
    ]
    assert "storage_path" not in body[0] and "thumbnail_path" not in body[0]


def test_student_events_and_media() -> None:
    client, token = _admin()
    events = client.get("/v1/students/st1/events", headers=_auth(token))
    assert events.status_code == 200
    assert [e["event_id"] for e in events.json()] == ["e1"]

    media = client.get("/v1/students/st1/media", headers=_auth(token))
    assert [m["media_id"] for m in media.json()] == ["m1"]

    filtered = client.get(
        "/v1/students/st1/media", params={"event_id": "e1"}, headers=_auth(token)
    )
    assert [m["media_id"] for m in filtered.json()] == ["m1"]
    empty = client.get(
        "/v1/students/st1/media", params={"event_id": "other"}, headers=_auth(token)
    )
    assert empty.status_code == 404  # foreign event -> 404 (guarded)


def test_media_appearances() -> None:
    client, token = _admin()
    resp = client.get("/v1/media/m1/appearances", headers=_auth(token))
    assert resp.status_code == 200
    assert [a["student_id"] for a in resp.json()] == ["st1"]


# ---- download ----------------------------------------------------------


def test_staff_downloads_any_media() -> None:
    client, token = _admin()
    # m2 has no matches, but staff may still download it.
    resp = client.get("/v1/media/m2/download", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["download_url"] and body["expires_in_s"] == 3600


def test_student_downloads_only_own_appearance() -> None:
    client = _build()
    token = _token(client, "stu")
    ok = client.get("/v1/media/m1/download", headers=_auth(token))
    assert ok.status_code == 200, ok.text
    # m2: student doesn't appear -> 404 (not 403; never confirms existence).
    denied = client.get("/v1/media/m2/download", headers=_auth(token))
    assert denied.status_code == 404


# ---- tenant / RBAC / auth ----------------------------------------------


def test_foreign_event_is_404() -> None:
    client, token = _admin()
    assert client.get("/v1/events/ghost/students", headers=_auth(token)).status_code == 404


def test_cross_school_staff_cannot_see_another_schools_data() -> None:
    # A school-B admin requesting school A's REAL ids (not just non-existent ones) must
    # get 404 across every gallery + download route — never a 200 or a leak (0028).
    client = _build()
    token = _token(client, "sa2")  # school_admin of school s2
    for path in (
        "/v1/events/e1/students",
        "/v1/events/e1/students/st1/media",
        "/v1/students/st1/events",
        "/v1/students/st1/media",
        "/v1/media/m1/appearances",
        "/v1/media/m1/download",
    ):
        assert client.get(path, headers=_auth(token)).status_code == 404, path


def test_student_forbidden_from_staff_gallery() -> None:
    client = _build()
    token = _token(client, "stu")
    assert client.get("/v1/events/e1/students", headers=_auth(token)).status_code == 403


def test_platform_admin_forbidden_from_gallery_and_download() -> None:
    container = SeededContainer(
        FakeUserRepo([_user(id="pa", role=Role.PLATFORM_ADMIN, school_id=None)]),
    )
    app = create_app()
    app.dependency_overrides[get_container_dep] = lambda: container
    client = TestClient(app)
    token = _token(client, "pa")
    assert client.get("/v1/events/e1/students", headers=_auth(token)).status_code == 403
    assert client.get("/v1/media/m1/download", headers=_auth(token)).status_code == 403


def test_gallery_requires_auth() -> None:
    client = _build()
    assert client.get("/v1/events/e1/students").status_code == 401
    assert client.get("/v1/media/m1/download").status_code == 401
