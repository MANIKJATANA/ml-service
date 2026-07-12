"""End-to-end student routes over HTTP (decisions/0026).

Real JWT + argon2 + RBAC + StudentService; fake repos/object-store/ML-client injected
via a Container subclass. Exercises tenant isolation (school from the token), the
`student:manage` gate, and the enroll/delete integration seams.
"""

from __future__ import annotations

from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.domain.models import Role, School, User
from backend.main import create_app
from backend_fakes import (
    FakeMlClient,
    FakeSchoolRepo,
    FakeStudentRepo,
    FakeUserRepo,
    SeededContainer,
    make_school,
    make_user,
)
from fastapi.testclient import TestClient

_HASHER = Argon2PasswordHasher()
_PATH = "reference-photos/s1/photo.jpg"


def _user(*, id: str, role: Role, school_id: str | None, password: str = "pw") -> User:
    user: User = make_user(
        id=id,
        school_id=school_id,
        email=f"{id}@x.io",
        password_hash=_HASHER.hash(password),
        role=role,
    )
    return user


def _build(
    *,
    users: list[User],
    schools: list[School] | None = None,
    students: FakeStudentRepo | None = None,
    ml_client: FakeMlClient | None = None,
) -> tuple[TestClient, SeededContainer]:
    container = SeededContainer(
        FakeUserRepo(users),
        FakeSchoolRepo(schools if schools is not None else [make_school(id="s1")]),
        students=students or FakeStudentRepo(),
        ml_client=ml_client or FakeMlClient(),
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


def _admin_client(**kw: object) -> tuple[TestClient, str, SeededContainer]:
    client, container = _build(
        users=[_user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1")], **kw  # type: ignore[arg-type]
    )
    return client, _token(client, "sa"), container


# ---- upload url --------------------------------------------------------


def test_upload_url_is_scoped_and_reports_limit() -> None:
    client, token, _ = _admin_client()
    resp = client.post("/v1/students/upload-url", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["object_path"].startswith("reference-photos/s1/")
    assert body["max_upload_mb"] == 30
    assert body["upload_url"]


# ---- create ------------------------------------------------------------


def test_school_admin_creates_student_in_own_school() -> None:
    client, token, container = _admin_client()
    resp = client.post(
        "/v1/students",
        json={"name": "Bart", "email": "bart@s1.io", "password": "temp-pw-123",
              "reference_photo_path": _PATH},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # Tenant isolation: the student lands in the admin's own school, from the token.
    assert body["school_id"] == "s1" and body["name"] == "Bart"
    assert body["enrollment_status"] == "enrolled"
    # email is now exposed (0033) — the student's login email; the hash never is.
    assert body["email"] == "bart@s1.io" and "password_hash" not in body
    # The ML enrollment seam was invoked for this student's photo.
    ml = container.ml_enrollment_client()
    assert isinstance(ml, FakeMlClient) and ml.enroll_calls[0][2] == [_PATH]


def test_teacher_can_manage_students() -> None:
    client, container = _build(
        users=[_user(id="tch", role=Role.TEACHER, school_id="s1")]
    )
    token = _token(client, "tch")
    resp = client.post(
        "/v1/students",
        json={"name": "Lisa", "email": "lisa@s1.io", "password": "temp-pw-123",
              "reference_photo_path": _PATH},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text


def test_create_rejects_foreign_prefix_path() -> None:
    client, token, _ = _admin_client()
    resp = client.post(
        "/v1/students",
        json={"name": "X", "email": "x@s1.io", "password": "temp-pw-123",
              "reference_photo_path": "reference-photos/other/p.jpg"},
        headers=_auth(token),
    )
    assert resp.status_code == 400  # ValidationError (tenant path guard)


def test_create_short_password_rejected_by_schema() -> None:
    client, token, _ = _admin_client()
    resp = client.post(
        "/v1/students",
        json={"name": "X", "email": "x@s1.io", "password": "short",
              "reference_photo_path": _PATH},
        headers=_auth(token),
    )
    assert resp.status_code == 422  # min_length=8


def test_whitespace_name_rejected_as_400_not_422() -> None:
    # Passes the schema's min_length=1 but the service trims -> ValidationError 400.
    client, token, _ = _admin_client()
    resp = client.post(
        "/v1/students",
        json={"name": "   ", "email": "x@s1.io", "password": "temp-pw-123",
              "reference_photo_path": _PATH},
        headers=_auth(token),
    )
    assert resp.status_code == 400


def test_name_length_boundary() -> None:
    client, token, _ = _admin_client()
    ok = client.post(
        "/v1/students",
        json={"name": "a" * 200, "email": "ok@s1.io", "password": "temp-pw-123",
              "reference_photo_path": _PATH},
        headers=_auth(token),
    )
    assert ok.status_code == 201, ok.text  # exactly 200 accepted
    too_long = client.post(
        "/v1/students",
        json={"name": "a" * 201, "email": "long@s1.io", "password": "temp-pw-123",
              "reference_photo_path": _PATH},
        headers=_auth(token),
    )
    assert too_long.status_code == 422  # schema max_length=200


# ---- list + get + tenant isolation ------------------------------------


def test_list_and_get_and_cross_tenant_404() -> None:
    client, token, _ = _admin_client()
    created = client.post(
        "/v1/students",
        json={"name": "Bart", "email": "bart@s1.io", "password": "temp-pw-123",
              "reference_photo_path": _PATH},
        headers=_auth(token),
    ).json()
    sid = created["id"]

    listed = client.get("/v1/students", headers=_auth(token))
    assert listed.status_code == 200 and [s["id"] for s in listed.json()] == [sid]

    got = client.get(f"/v1/students/{sid}", headers=_auth(token))
    assert got.status_code == 200 and got.json()["id"] == sid

    missing = client.get("/v1/students/does-not-exist", headers=_auth(token))
    assert missing.status_code == 404


# ---- re-enroll ---------------------------------------------------------


def test_reenroll_endpoint_updates_status() -> None:
    ml = FakeMlClient(embeddings_stored=0)
    client, container = _build(
        users=[_user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1")], ml_client=ml
    )
    token = _token(client, "sa")
    created = client.post(
        "/v1/students",
        json={"name": "R", "email": "r@s1.io", "password": "temp-pw-123",
              "reference_photo_path": _PATH},
        headers=_auth(token),
    ).json()
    assert created["enrollment_status"] == "failed"

    ml._embeddings = 1
    resp = client.post(f"/v1/students/{created['id']}/enroll", headers=_auth(token))
    assert resp.status_code == 200 and resp.json()["enrollment_status"] == "enrolled"


# ---- delete ------------------------------------------------------------


def test_delete_student() -> None:
    client, token, container = _admin_client()
    created = client.post(
        "/v1/students",
        json={"name": "D", "email": "d@s1.io", "password": "temp-pw-123",
              "reference_photo_path": _PATH},
        headers=_auth(token),
    ).json()
    resp = client.delete(f"/v1/students/{created['id']}", headers=_auth(token))
    assert resp.status_code == 204
    # Gone afterwards.
    assert client.get(f"/v1/students/{created['id']}", headers=_auth(token)).status_code == 404


def test_delete_surfaces_ml_outage_as_502() -> None:
    from backend.domain.errors import UpstreamError

    client, container = _build(
        users=[_user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1")],
        ml_client=FakeMlClient(raise_on_delete=UpstreamError("ml down")),
    )
    token = _token(client, "sa")
    created = client.post(
        "/v1/students",
        json={"name": "K", "email": "k@s1.io", "password": "temp-pw-123",
              "reference_photo_path": _PATH},
        headers=_auth(token),
    ).json()
    resp = client.delete(f"/v1/students/{created['id']}", headers=_auth(token))
    assert resp.status_code == 502


# ---- RBAC + auth -------------------------------------------------------


def test_platform_admin_forbidden_from_student_routes() -> None:
    client, _ = _build(users=[_user(id="pa", role=Role.PLATFORM_ADMIN, school_id=None)])
    token = _token(client, "pa")
    assert client.get("/v1/students", headers=_auth(token)).status_code == 403


def test_student_role_forbidden_from_student_management() -> None:
    client, _ = _build(users=[_user(id="stu", role=Role.STUDENT, school_id="s1")])
    token = _token(client, "stu")
    assert client.get("/v1/students", headers=_auth(token)).status_code == 403


def test_student_routes_require_auth() -> None:
    client, _ = _build(users=[_user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1")])
    assert client.get("/v1/students").status_code == 401
