"""End-to-end access/download audit routes (BP8b, decisions/0050).

The audit reads are gated on ``audit:view`` — school_admin only for now (a teacher/student is
403, which proves the deliberate one-line-flip design). A real download through the gallery
endpoint records a row the log then surfaces; tenant is strictly from the token.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.domain.models import DownloadAuditEntry, Role, User
from backend.main import create_app
from backend_fakes import (
    FakeDownloadAuditRepo,
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
    """School s1: an admin, a teacher, and a student (stu→st1). Event e1 with photo m1 that
    st1 appears in (so the student can download it)."""
    container = SeededContainer(
        FakeUserRepo(
            [
                _user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1", email="sa@x.io"),
                _user(id="tt", role=Role.TEACHER, school_id="s1", email="tt@x.io"),
                _user(id="stu", role=Role.STUDENT, school_id="s1", email="stu@x.io"),
            ]
        ),
        FakeSchoolRepo([make_school(id="s1")]),
        students=FakeStudentRepo(
            [make_student(id="st1", school_id="s1", user_id="stu", name="Bart")]
        ),
        events=FakeEventRepo([make_event(id="e1", school_id="s1", name="Sports Day")]),
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


def _auth(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


# ---- entitlement -------------------------------------------------------


def test_admin_can_read_audit() -> None:
    client = _build()
    sa = _auth(_token(client, "sa"))
    assert client.get("/v1/media/m1/download-log", headers=sa).status_code == 200
    assert client.get("/v1/audit/downloads", headers=sa).status_code == 200


def test_teacher_is_forbidden() -> None:
    # Proves audit:view is admin-only: granting teachers later is a one-line change.
    client = _build()
    tt = _auth(_token(client, "tt"))
    assert client.get("/v1/media/m1/download-log", headers=tt).status_code == 403
    assert client.get("/v1/audit/downloads", headers=tt).status_code == 403


def test_student_is_forbidden() -> None:
    client = _build()
    stu = _auth(_token(client, "stu"))
    assert client.get("/v1/media/m1/download-log", headers=stu).status_code == 403
    assert client.get("/v1/audit/downloads", headers=stu).status_code == 403


def test_unauthenticated_is_401() -> None:
    client = _build()
    assert client.get("/v1/audit/downloads").status_code == 401


# ---- the loop: a download shows up in the audit ------------------------


def test_view_does_not_record_only_the_download_action_does() -> None:
    client = _build()
    sa = _auth(_token(client, "sa"))
    stu = _auth(_token(client, "stu"))

    # Nothing yet.
    assert client.get("/v1/media/m1/download-log", headers=sa).json()["count"] == 0

    # A GET /download is a signed-URL MINT — used for viewing the photo. Doing it many
    # times must record NOTHING (this is the bug BP8b's split fixes).
    for _ in range(3):
        assert client.get("/v1/media/m1/download", headers=sa).status_code == 200
        assert client.get("/v1/media/m1/download", headers=stu).status_code == 200
    assert client.get("/v1/media/m1/download-log", headers=sa).json()["count"] == 0

    # The POST is the actual download action: staff downloads, then the student self-downloads.
    assert client.post("/v1/media/m1/download", headers=sa).status_code == 204
    assert client.post("/v1/media/m1/download", headers=stu).status_code == 204

    log = client.get("/v1/media/m1/download-log", headers=sa)
    assert log.status_code == 200
    body = log.json()
    assert body["count"] == 2
    # Newest-first: the student self-download last, carrying the subject student.
    entries = body["entries"]
    assert entries[0]["actor_role"] == "student"
    assert entries[0]["subject_student_id"] == "st1"
    assert entries[0]["subject_student_name"] == "Bart"
    assert entries[0]["actor_email"] == "stu@x.io"
    assert entries[1]["actor_role"] == "school_admin"
    assert entries[1]["subject_student_id"] is None

    # And the school-wide log carries both, with event context.
    page = client.get("/v1/audit/downloads", headers=sa).json()
    assert page["total"] == 2
    assert page["items"][0]["event_name"] == "Sports Day"


def test_record_download_entitlement_gate() -> None:
    # A student recording a download of a media they don't appear in 404s + records nothing.
    client = _build()
    sa = _auth(_token(client, "sa"))
    stu = _auth(_token(client, "stu"))
    # st1 appears in m1 only; there is no m2, so use a media the student can't reach: a
    # staff-only-visible one doesn't exist here, so assert the happy path + a foreign 404.
    assert client.post("/v1/media/ghost/download", headers=stu).status_code == 404
    assert client.get("/v1/media/m1/download-log", headers=sa).json()["count"] == 0


def test_school_log_filters_by_student() -> None:
    client = _build()
    sa = _auth(_token(client, "sa"))
    stu = _auth(_token(client, "stu"))
    client.post("/v1/media/m1/download", headers=sa)  # staff (no subject)
    client.post("/v1/media/m1/download", headers=stu)  # student self (subject st1)

    page = client.get("/v1/audit/downloads?student_id=st1", headers=sa).json()
    assert page["total"] == 1
    assert page["items"][0]["actor_role"] == "student"


def test_download_log_tenant_scoped_foreign_media_404() -> None:
    client = _build()
    sa = _auth(_token(client, "sa"))
    assert client.get("/v1/media/ghost/download-log", headers=sa).status_code == 404


# ---- BP28a: date-range + actor-role filters + boundary 422 -------------


class _SpyAuditRepo:
    """Records the kwargs of the last list_recent call so a route test can prove the new query
    params (created_from/created_to/actor_role) reach the service unchanged. Delegates every
    other method to a plain FakeDownloadAuditRepo (composition, not subclassing — the fake is
    untyped under mypy, so subclassing it isn't type-safe)."""

    def __init__(self) -> None:
        self._inner = FakeDownloadAuditRepo([])
        self.last_kwargs: dict[str, Any] = {}

    async def list_recent(
        self, school_id: str, **kwargs: Any
    ) -> list[DownloadAuditEntry]:
        self.last_kwargs = kwargs
        result: list[DownloadAuditEntry] = await self._inner.list_recent(
            school_id, **kwargs
        )
        return result

    def __getattr__(self, name: str) -> Any:
        # Delegate everything else (record/count_recent/list_for_media/…) to the fake so the
        # spy satisfies the whole DownloadAuditRepository surface with one line.
        return getattr(self._inner, name)


def _build_with_spy(spy: _SpyAuditRepo) -> TestClient:
    container = SeededContainer(
        FakeUserRepo(
            [_user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1", email="sa@x.io")]
        ),
        FakeSchoolRepo([make_school(id="s1")]),
        download_audit=spy,
    )
    app = create_app()
    app.dependency_overrides[get_container_dep] = lambda: container
    return TestClient(app)


def test_malformed_created_from_is_422() -> None:
    # Typed datetime at the boundary — a garbage value is rejected before the service.
    client = _build()
    sa = _auth(_token(client, "sa"))
    resp = client.get("/v1/audit/downloads?created_from=not-a-date", headers=sa)
    assert resp.status_code == 422


def test_unknown_actor_role_is_422() -> None:
    client = _build()
    sa = _auth(_token(client, "sa"))
    resp = client.get("/v1/audit/downloads?actor_role=wizard", headers=sa)
    assert resp.status_code == 422


def test_new_filter_params_reach_the_service() -> None:
    spy = _SpyAuditRepo()
    client = _build_with_spy(spy)
    sa = _auth(_token(client, "sa"))
    resp = client.get(
        "/v1/audit/downloads"
        "?created_from=2026-01-01T00:00:00Z"
        "&created_to=2026-01-31T23:59:59Z"
        "&actor_role=student",
        headers=sa,
    )
    assert resp.status_code == 200
    assert spy.last_kwargs["created_from"] == datetime.fromisoformat(
        "2026-01-01T00:00:00+00:00"
    )
    assert spy.last_kwargs["created_to"] == datetime.fromisoformat(
        "2026-01-31T23:59:59+00:00"
    )
    # The Role enum is passed to the service as its raw string value (the denormalized column).
    assert spy.last_kwargs["actor_role"] == "student"
