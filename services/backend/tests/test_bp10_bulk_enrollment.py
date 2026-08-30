"""BP10 bulk photo enrollment: filename→student matching + orphan cleanup (decisions/0057).

Service-level ``resolve_photo_targets`` (email / UUID / case-insensitive / unmatched /
tenant-scoped / order-preserving) and ``delete_reference_photo_upload`` (tenant-guarded), then
the two routes end-to-end (``POST /match-photos``, the cleanup ``DELETE``, the batch-cap 422,
and the ``student:manage`` gate). No new enroll/upload path — the FE loops the existing
per-student routes, so those stay covered by ``test_student_*``.
"""

from __future__ import annotations

import uuid

import pytest
from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.domain.errors import ValidationError
from backend.domain.models import EnrollmentStatus, Role, School, Student, User
from backend.main import create_app
from backend.services.student_service import StudentService
from backend.settings import settings
from backend_fakes import (
    FakeAdminActionAuditRepo,
    FakeHasher,
    FakeMlClient,
    FakeObjectStore,
    FakeSchoolRepo,
    FakeStudentGroupRepo,
    FakeStudentRepo,
    FakeThumbnailer,
    FakeUserRepo,
    SeededContainer,
    make_school,
    make_student,
    make_user,
)
from fastapi.testclient import TestClient

_S1 = "s1"


# ---- service: resolve_photo_targets -----------------------------------


def _svc(
    students: list[Student] | None = None, *, store: FakeObjectStore | None = None
) -> StudentService:
    return StudentService(
        FakeStudentRepo(students or []),
        FakeUserRepo(),
        FakeSchoolRepo([make_school(id=_S1)]),
        FakeHasher(),
        store or FakeObjectStore(),
        FakeMlClient(),
        FakeThumbnailer(),
        FakeStudentGroupRepo(),
        FakeAdminActionAuditRepo(),
        reference_photo_prefix="reference-photos",
    )


async def test_resolve_matches_email_case_insensitively() -> None:
    svc = _svc([make_student(id="stu-1", school_id=_S1, email="alice@x.io")])
    targets = await svc.resolve_photo_targets(school_id=_S1, filenames=["Alice@X.io.jpg"])
    assert len(targets) == 1
    assert targets[0].student is not None and targets[0].student.id == "stu-1"


async def test_resolve_matches_by_student_id_uuid() -> None:
    sid = str(uuid.uuid4())
    svc = _svc([make_student(id=sid, school_id=_S1, email="x@x.io")])
    targets = await svc.resolve_photo_targets(school_id=_S1, filenames=[f"{sid}.png"])
    assert targets[0].student is not None and targets[0].student.id == sid


async def test_resolve_unmatched_is_surfaced_not_dropped() -> None:
    svc = _svc([make_student(id="stu-1", school_id=_S1, email="alice@x.io")])
    targets = await svc.resolve_photo_targets(school_id=_S1, filenames=["ghost@x.io.jpg"])
    assert len(targets) == 1 and targets[0].student is None


async def test_resolve_is_tenant_scoped_no_cross_tenant_leak() -> None:
    # A student in ANOTHER school with the queried email must not match — resolving only ever
    # sees the caller's school, so a foreign email comes back unmatched (no enumeration).
    svc = _svc([make_student(id="stu-2", school_id="s2", email="bob@x.io")])
    targets = await svc.resolve_photo_targets(school_id=_S1, filenames=["bob@x.io.jpg"])
    assert targets[0].student is None


async def test_resolve_preserves_order_for_a_mixed_batch() -> None:
    sid = str(uuid.uuid4())
    svc = _svc(
        [
            make_student(id="stu-1", school_id=_S1, email="alice@x.io"),
            make_student(id=sid, school_id=_S1, email="carol@x.io"),
        ]
    )
    targets = await svc.resolve_photo_targets(
        school_id=_S1,
        filenames=["alice@x.io.jpg", "ghost@x.io.png", f"{sid}.jpeg"],
    )
    assert [t.filename for t in targets] == [
        "alice@x.io.jpg",
        "ghost@x.io.png",
        f"{sid}.jpeg",
    ]
    assert [t.student.id if t.student else None for t in targets] == ["stu-1", None, sid]


async def test_resolve_surfaces_the_matched_students_enrollment_status() -> None:
    # The FE warns "already enrolled → will replace" off this.
    svc = _svc(
        [
            make_student(
                id="stu-1",
                school_id=_S1,
                email="e@x.io",
                enrollment_status=EnrollmentStatus.ENROLLED,
            )
        ]
    )
    targets = await svc.resolve_photo_targets(school_id=_S1, filenames=["e@x.io.jpg"])
    assert targets[0].student is not None
    assert targets[0].student.enrollment_status is EnrollmentStatus.ENROLLED


async def test_resolve_email_with_domain_suffix_is_matched_whole() -> None:
    # Only a known image suffix is stripped (never a bare ``.edu``): both an email-named file
    # WITH an image extension and one WITHOUT still map to the email.
    svc = _svc([make_student(id="stu-1", school_id=_S1, email="a@b.edu")])
    with_ext = await svc.resolve_photo_targets(school_id=_S1, filenames=["a@b.edu.jpg"])
    no_ext = await svc.resolve_photo_targets(school_id=_S1, filenames=["a@b.edu"])
    assert with_ext[0].student is not None and no_ext[0].student is not None


async def test_resolve_empty_batch_returns_empty() -> None:
    svc = _svc([make_student(id="stu-1", school_id=_S1, email="alice@x.io")])
    assert await svc.resolve_photo_targets(school_id=_S1, filenames=[]) == []


async def test_resolve_two_filenames_to_same_student_both_match() -> None:
    # The service returns a per-filename mapping (dedup is the caller's job): two different
    # filenames for one student's email both resolve to that student. The FE keeps the first
    # and unmatches the rest — a contract both sides rely on.
    svc = _svc([make_student(id="stu-1", school_id=_S1, email="alice@x.io")])
    targets = await svc.resolve_photo_targets(
        school_id=_S1, filenames=["alice@x.io.jpg", "Alice@X.io.png"]
    )
    assert [t.student.id if t.student else None for t in targets] == ["stu-1", "stu-1"]


async def test_resolve_preserves_a_duplicate_filename() -> None:
    svc = _svc([make_student(id="stu-1", school_id=_S1, email="alice@x.io")])
    targets = await svc.resolve_photo_targets(
        school_id=_S1, filenames=["alice@x.io.jpg", "alice@x.io.jpg"]
    )
    assert len(targets) == 2 and all(t.student is not None for t in targets)


# ---- service: delete_reference_photo_upload ---------------------------


async def test_cleanup_deletes_object_under_own_prefix() -> None:
    store = FakeObjectStore()
    svc = _svc(store=store)
    await svc.delete_reference_photo_upload(
        school_id=_S1, object_path="reference-photos/s1/abc-123"
    )
    assert store.deleted == ["reference-photos/s1/abc-123"]


async def test_cleanup_rejects_a_foreign_prefix_before_any_delete() -> None:
    store = FakeObjectStore()
    svc = _svc(store=store)
    with pytest.raises(ValidationError):
        await svc.delete_reference_photo_upload(
            school_id=_S1, object_path="reference-photos/other-school/abc"
        )
    assert store.deleted == []  # rejected by the prefix guard, nothing touched


async def test_cleanup_is_best_effort_when_the_store_fails() -> None:
    # The FE fires cleanup fire-and-forget, so a store outage must not surface as an error —
    # the delete is attempted, the failure logged + swallowed (never raised to the caller).
    store = FakeObjectStore(fail_deletes=True)
    svc = _svc(store=store)
    await svc.delete_reference_photo_upload(
        school_id=_S1, object_path="reference-photos/s1/orphan"
    )  # does NOT raise
    assert store.delete_attempts == 1  # attempted once, then swallowed


# ---- routes ------------------------------------------------------------

_HASHER = Argon2PasswordHasher()


def _user(*, id: str, role: Role, school_id: str | None) -> User:
    user: User = make_user(
        id=id, school_id=school_id, email=f"{id}@x.io",
        password_hash=_HASHER.hash("pw"), role=role,
    )
    return user


def _build(
    *,
    users: list[User],
    schools: list[School] | None = None,
    students: FakeStudentRepo | None = None,
) -> tuple[TestClient, SeededContainer]:
    container = SeededContainer(
        FakeUserRepo(users),
        FakeSchoolRepo(schools if schools is not None else [make_school(id="s1")]),
        students=students or FakeStudentRepo(),
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


def _admin_client(
    *, students: FakeStudentRepo | None = None
) -> tuple[TestClient, str, SeededContainer]:
    client, container = _build(
        users=[_user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1")], students=students
    )
    return client, _token(client, "sa"), container


def test_match_photos_maps_filenames_to_students() -> None:
    client, token, _ = _admin_client()
    created = client.post(
        "/v1/students", json={"name": "NP", "email": "np@s1.io"}, headers=_auth(token)
    ).json()["student"]
    resp = client.post(
        "/v1/students/match-photos",
        json={"filenames": ["NP@s1.io.jpg", "ghost@s1.io.jpg"]},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    results = resp.json()["results"]
    assert [r["filename"] for r in results] == ["NP@s1.io.jpg", "ghost@s1.io.jpg"]
    assert results[0]["matched"] is True
    assert results[0]["student_id"] == created["id"]
    assert results[0]["student_name"] == "NP"
    assert results[0]["enrollment_status"] == "pending"
    assert results[1]["matched"] is False
    assert results[1]["student_id"] is None and results[1]["student_name"] is None


def test_match_photos_matches_by_uuid_stem_via_route() -> None:
    # A `{student_id}.jpg` filename resolves by id — exercised end-to-end through the route +
    # the from_target serialization (the service-level UUID match is covered separately).
    sid = str(uuid.uuid4())
    students = FakeStudentRepo([make_student(id=sid, school_id="s1", email="uu@s1.io")])
    client, token, _ = _admin_client(students=students)
    resp = client.post(
        "/v1/students/match-photos",
        json={"filenames": [f"{sid}.jpg"]},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["results"][0]
    assert result["matched"] is True and result["student_id"] == sid


def test_match_photos_over_the_batch_cap_is_422() -> None:
    # The batch is capped at the configurable bulk_photo_max_files (schema max_length).
    client, token, _ = _admin_client()
    over = [f"a{i}@s1.io.jpg" for i in range(settings.bulk_photo_max_files + 1)]
    resp = client.post(
        "/v1/students/match-photos", json={"filenames": over}, headers=_auth(token)
    )
    assert resp.status_code == 422


def test_match_photos_empty_batch_is_422() -> None:
    client, token, _ = _admin_client()
    resp = client.post(
        "/v1/students/match-photos", json={"filenames": []}, headers=_auth(token)
    )
    assert resp.status_code == 422


def test_match_photos_requires_student_manage() -> None:
    client, _ = _build(users=[_user(id="stu", role=Role.STUDENT, school_id="s1")])
    token = _token(client, "stu")
    resp = client.post(
        "/v1/students/match-photos",
        json={"filenames": ["a@s1.io.jpg"]},
        headers=_auth(token),
    )
    assert resp.status_code == 403


def test_cleanup_deletes_object_under_own_prefix_via_route() -> None:
    client, token, container = _admin_client()
    # A 204 (not a 404) also proves the literal route wins over DELETE /{student_id}.
    resp = client.delete(
        "/v1/students/reference-photo-upload",
        params={"path": "reference-photos/s1/orphan-xyz"},
        headers=_auth(token),
    )
    assert resp.status_code == 204, resp.text
    store = container.object_store()
    assert isinstance(store, FakeObjectStore)
    assert store.deleted == ["reference-photos/s1/orphan-xyz"]


def test_cleanup_rejects_a_foreign_prefix_via_route() -> None:
    client, token, container = _admin_client()
    resp = client.delete(
        "/v1/students/reference-photo-upload",
        params={"path": "reference-photos/other-school/xyz"},
        headers=_auth(token),
    )
    assert resp.status_code == 400
    store = container.object_store()
    assert isinstance(store, FakeObjectStore)
    assert store.deleted == []


def test_cleanup_requires_student_manage() -> None:
    client, _ = _build(users=[_user(id="stu", role=Role.STUDENT, school_id="s1")])
    token = _token(client, "stu")
    resp = client.delete(
        "/v1/students/reference-photo-upload",
        params={"path": "reference-photos/s1/xyz"},
        headers=_auth(token),
    )
    assert resp.status_code == 403


def test_bulk_photo_routes_require_auth() -> None:
    client, _ = _build(users=[_user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1")])
    match = client.post("/v1/students/match-photos", json={"filenames": ["a.jpg"]})
    assert match.status_code == 401
    cleanup = client.delete(
        "/v1/students/reference-photo-upload", params={"path": "reference-photos/s1/x"}
    )
    assert cleanup.status_code == 401
