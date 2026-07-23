"""StudentService use-cases with fakes (decisions/0026, BP7b, BP7d)."""

from __future__ import annotations

import pytest
from backend.domain.errors import (
    ConflictError,
    NotFoundError,
    UpstreamError,
    ValidationError,
)
from backend.domain.models import (
    EnrollmentFailureReason,
    EnrollmentStatus,
    Role,
    School,
    SchoolStatus,
    Student,
    User,
)
from backend.services.student_service import StudentService
from backend_fakes import (
    FakeHasher,
    FakeMlClient,
    FakeObjectStore,
    FakeSchoolRepo,
    FakeStudentRepo,
    FakeUserRepo,
    make_school,
)

_S1 = "s1"
_PATH = "reference-photos/s1/photo.jpg"


def _svc(
    *,
    schools: list[School] | None = None,
    users: list[User] | None = None,
    ml_client: FakeMlClient | None = None,
    object_store: FakeObjectStore | None = None,
) -> tuple[StudentService, FakeStudentRepo, FakeUserRepo, FakeMlClient]:
    srepo = FakeSchoolRepo(schools or [make_school(id=_S1, max_teachers=5)])
    urepo = FakeUserRepo(users or [])
    strepo = FakeStudentRepo()
    urepo.link_cascade(strepo.remove_by_user)  # mirror the FK cascade
    strepo.link_users(urepo.email_of)  # mirror the users JOIN (email on student reads)
    ml = ml_client or FakeMlClient()
    svc = StudentService(
        strepo,
        urepo,
        srepo,
        FakeHasher(),
        object_store or FakeObjectStore(),
        ml,
        reference_photo_prefix="reference-photos",
    )
    return svc, strepo, urepo, ml


async def _create(svc: StudentService, **kwargs: object) -> Student:
    """Create a student and return the Student (create now returns ProvisionedStudent)."""
    prov = await svc.create_student(**kwargs)  # type: ignore[arg-type]
    return prov.student


# ---- upload url --------------------------------------------------------


async def test_create_upload_url_is_under_tenant_prefix() -> None:
    svc, _, _, _ = _svc()
    signed = await svc.create_upload_url(school_id=_S1)
    assert signed.object_path.startswith("reference-photos/s1/")
    assert signed.upload_url  # a target the FE can upload to


# ---- create + enroll ---------------------------------------------------


async def test_create_student_provisions_login_and_enrolls() -> None:
    svc, _, urepo, ml = _svc()
    prov = await svc.create_student(
        school_id=_S1, name="  Bart ", email="Bart@X.io", reference_photo_path=_PATH,
    )
    student = prov.student
    assert student.name == "Bart"  # trimmed
    assert student.school_id == _S1
    assert student.email == "bart@x.io"  # the login email, joined onto the read model
    assert student.enrollment_status is EnrollmentStatus.ENROLLED

    # A login account was created: role=student, server-generated temp password (BP7d).
    user = await urepo.get(student.user_id)
    assert user is not None
    assert user.role is Role.STUDENT and user.must_change_password is True
    assert user.email == "bart@x.io"
    assert len(prov.temp_password) >= 8
    assert user.password_hash == f"hash:{prov.temp_password}"  # hashed, never the raw pw

    # Enrollment used exactly the stored reference photo path.
    assert ml.enroll_calls == [(_S1, student.id, [_PATH])]


async def test_photoless_create_is_pending_and_skips_enrollment() -> None:
    # BP7d: omitting the reference photo creates a pending student with no ML call.
    svc, _, _, ml = _svc()
    prov = await svc.create_student(school_id=_S1, name="No Photo", email="np@x.io")
    assert prov.student.enrollment_status is EnrollmentStatus.PENDING
    assert prov.student.reference_photo_path is None
    assert len(prov.temp_password) >= 8
    assert ml.enroll_calls == []  # nothing to enroll


async def test_zero_embeddings_marks_failed() -> None:
    svc, _, _, _ = _svc(ml_client=FakeMlClient(embeddings_stored=0))
    student = await _create(
        svc, school_id=_S1, name="Lisa", email="lisa@x.io", reference_photo_path=_PATH,
    )
    assert student.enrollment_status is EnrollmentStatus.FAILED


async def test_ml_outage_still_creates_student_as_failed() -> None:
    # An ML outage must NOT block account creation (0026).
    ml = FakeMlClient(raise_on_enroll=UpstreamError("ml down"))
    svc, strepo, urepo, _ = _svc(ml_client=ml)
    student = await _create(
        svc, school_id=_S1, name="Milhouse", email="m@x.io", reference_photo_path=_PATH,
    )
    assert student.enrollment_status is EnrollmentStatus.FAILED
    assert await urepo.get(student.user_id) is not None  # login persisted
    assert await strepo.get(_S1, student.id) is not None  # profile persisted


async def test_path_outside_tenant_prefix_rejected_before_any_write() -> None:
    svc, strepo, urepo, ml = _svc()
    with pytest.raises(ValidationError):
        await svc.create_student(
            school_id=_S1, name="X", email="x@x.io",
            reference_photo_path="reference-photos/other-school/photo.jpg",
        )
    # Nothing was written and no enrollment attempted.
    assert await urepo.get_by_email("x@x.io") is None
    assert not await strepo.list_by_school(_S1)
    assert ml.enroll_calls == []


async def test_create_for_missing_school_rejected() -> None:
    svc, _, _, _ = _svc(schools=[])
    with pytest.raises(ValidationError):
        await svc.create_student(
            school_id="nope", name="X", email="x@x.io",
            reference_photo_path="reference-photos/nope/p.jpg",
        )


async def test_create_for_suspended_school_rejected() -> None:
    svc, _, _, _ = _svc(schools=[make_school(id=_S1, status=SchoolStatus.SUSPENDED)])
    with pytest.raises(ValidationError):
        await svc.create_student(
            school_id=_S1, name="X", email="x@x.io", reference_photo_path=_PATH,
        )


async def test_duplicate_email_conflicts_and_creates_no_student() -> None:
    svc, strepo, _, _ = _svc()
    await svc.create_student(
        school_id=_S1, name="A", email="dup@x.io", reference_photo_path=_PATH,
    )
    with pytest.raises(ConflictError):
        await svc.create_student(
            school_id=_S1, name="B", email="DUP@x.io", reference_photo_path=_PATH,
        )
    assert len(await strepo.list_by_school(_S1)) == 1  # no orphan profile


async def test_empty_name_rejected() -> None:
    svc, _, _, _ = _svc()
    with pytest.raises(ValidationError):
        await svc.create_student(
            school_id=_S1, name="   ", email="x@x.io", reference_photo_path=_PATH,
        )


async def test_profile_insert_failure_compensates_by_deleting_login() -> None:
    # If the students insert fails after the login is created, the orphan login is
    # removed (compensating action, 0026).
    svc, strepo, urepo, _ = _svc()
    strepo.fail_create = True
    with pytest.raises(RuntimeError):
        await svc.create_student(
            school_id=_S1, name="X", email="orphan@x.io", reference_photo_path=_PATH,
        )
    assert await urepo.get_by_email("orphan@x.io") is None  # login rolled back


async def test_compensating_delete_failure_preserves_original_error() -> None:
    # If the compensating delete itself blows up, the ORIGINAL profile-insert error
    # must still propagate (not be masked by the delete's error) (0026 review r1).
    svc, strepo, urepo, _ = _svc()
    strepo.fail_create = True

    async def _boom_delete(user_id: str) -> None:
        raise RuntimeError("delete blew up")

    urepo.delete = _boom_delete  # shadow the method for this test
    with pytest.raises(RuntimeError, match="simulated students-insert failure"):
        await svc.create_student(
            school_id=_S1, name="X", email="x@x.io", reference_photo_path=_PATH,
        )


# ---- bulk import (BP7d) ------------------------------------------------


async def test_bulk_create_all_created_photoless_and_pending() -> None:
    svc, strepo, _, ml = _svc()
    results = await svc.bulk_create_students(
        school_id=_S1, rows=[("Alice", "alice@x.io"), ("Bob", "bob@x.io")],
    )
    assert [r.status for r in results] == ["created", "created"]
    assert all(r.temp_password and len(r.temp_password) >= 8 for r in results)
    assert all(r.student_id for r in results)
    # Every created student is photoless + pending, and NO enrollment fired.
    students = await strepo.list_by_school(_S1)
    assert len(students) == 2
    assert all(s.reference_photo_path is None for s in students)
    assert all(s.enrollment_status is EnrollmentStatus.PENDING for s in students)
    assert ml.enroll_calls == []


async def test_bulk_create_isolates_duplicate_invalid_and_error_rows() -> None:
    svc, strepo, _, _ = _svc()
    await svc.create_student(school_id=_S1, name="Existing", email="dup@x.io")  # pre-seed
    results = await svc.bulk_create_students(
        school_id=_S1,
        rows=[
            ("New", "new@x.io"),  # created
            ("Dupe", "DUP@x.io"),  # duplicate (case-insensitive)
            ("Bad Email", "not-an-email"),  # invalid
            ("   ", "blank@x.io"),  # invalid (empty name)
        ],
    )
    assert [r.status for r in results] == ["created", "duplicate", "invalid", "invalid"]
    # A bad row never aborts the batch: 1 pre-seeded + 1 new = 2 students total.
    assert len(await strepo.list_by_school(_S1)) == 2
    # The invalid rows carry a reason; the created row carries a temp password.
    assert results[0].temp_password and results[2].error


async def test_bulk_create_rejected_up_front_for_suspended_school() -> None:
    svc, _, _, _ = _svc(schools=[make_school(id=_S1, status=SchoolStatus.SUSPENDED)])
    with pytest.raises(ValidationError):
        await svc.bulk_create_students(school_id=_S1, rows=[("A", "a@x.io")])


# ---- re-enroll ---------------------------------------------------------


async def test_reenroll_retries_with_stored_path_and_updates_status() -> None:
    ml = FakeMlClient(embeddings_stored=0)
    svc, _, _, _ = _svc(ml_client=ml)
    created = await _create(
        svc, school_id=_S1, name="R", email="r@x.io", reference_photo_path=_PATH,
    )
    assert created.enrollment_status is EnrollmentStatus.FAILED

    ml._embeddings = 1  # ML now succeeds on retry
    refreshed = await svc.enroll_student(school_id=_S1, student_id=created.id)
    assert refreshed.enrollment_status is EnrollmentStatus.ENROLLED
    # Re-enroll reused the stored reference path.
    assert ml.enroll_calls[-1] == (_S1, created.id, [_PATH])


async def test_reenroll_missing_student_raises() -> None:
    svc, _, _, _ = _svc()
    with pytest.raises(NotFoundError):
        await svc.enroll_student(school_id=_S1, student_id="ghost")


async def test_enroll_photoless_student_is_rejected() -> None:
    # BP7d: a bulk-imported (photoless) student has nothing to enroll -> 400, no ML call.
    svc, _, _, ml = _svc()
    prov = await svc.create_student(school_id=_S1, name="NP", email="np@x.io")
    with pytest.raises(ValidationError):
        await svc.enroll_student(school_id=_S1, student_id=prov.student.id)
    assert ml.enroll_calls == []


# ---- set / replace reference photo (BP7d-2) ---------------------------


async def test_set_reference_photo_enrolls_a_photoless_student() -> None:
    svc, _, _, ml = _svc()
    prov = await svc.create_student(school_id=_S1, name="NP", email="np@x.io")
    assert prov.student.enrollment_status is EnrollmentStatus.PENDING
    updated = await svc.set_reference_photo(
        school_id=_S1, student_id=prov.student.id, reference_photo_path=_PATH,
    )
    assert updated.reference_photo_path == _PATH
    assert updated.enrollment_status is EnrollmentStatus.ENROLLED
    assert ml.enroll_calls[-1] == (_S1, prov.student.id, [_PATH])


async def test_set_reference_photo_fixes_a_failed_enrollment() -> None:
    # BP7d-2 closes BP7b's loop: swapping a bad photo re-enrolls + clears the reason.
    ml = FakeMlClient(embeddings_stored=0, photo_status="no_face")
    svc, _, _, _ = _svc(ml_client=ml)
    created = await _create(
        svc, school_id=_S1, name="F", email="f@x.io", reference_photo_path=_PATH,
    )
    assert created.enrollment_status is EnrollmentStatus.FAILED
    assert created.enrollment_failure_reason is EnrollmentFailureReason.NO_FACE

    ml._embeddings = 1
    ml._photo_status = "enrolled"
    fixed = await svc.set_reference_photo(
        school_id=_S1, student_id=created.id, reference_photo_path=_PATH,
    )
    assert fixed.enrollment_status is EnrollmentStatus.ENROLLED
    assert fixed.enrollment_failure_reason is None


async def test_set_reference_photo_replaces_on_an_already_enrolled_student() -> None:
    # Swapping a good photo for another on an enrolled student re-enrolls with the new one.
    svc, _, _, ml = _svc()
    created = await _create(
        svc, school_id=_S1, name="E", email="e@x.io", reference_photo_path=_PATH,
    )
    assert created.enrollment_status is EnrollmentStatus.ENROLLED
    new_path = "reference-photos/s1/photo2.jpg"
    updated = await svc.set_reference_photo(
        school_id=_S1, student_id=created.id, reference_photo_path=new_path,
    )
    assert updated.reference_photo_path == new_path
    assert updated.enrollment_status is EnrollmentStatus.ENROLLED
    assert ml.enroll_calls[-1] == (_S1, created.id, [new_path])


async def test_set_reference_photo_rejects_foreign_prefix() -> None:
    svc, _, _, ml = _svc()
    prov = await svc.create_student(school_id=_S1, name="NP", email="np@x.io")
    with pytest.raises(ValidationError):
        await svc.set_reference_photo(
            school_id=_S1,
            student_id=prov.student.id,
            reference_photo_path="reference-photos/other-school/p.jpg",
        )
    assert ml.enroll_calls == []  # rejected before any ML call


async def test_set_reference_photo_is_tenant_scoped() -> None:
    svc, _, _, _ = _svc(schools=[make_school(id=_S1), make_school(id="s2")])
    prov = await svc.create_student(school_id=_S1, name="T", email="t@x.io")
    with pytest.raises(NotFoundError):
        await svc.set_reference_photo(
            school_id="s2",
            student_id=prov.student.id,
            reference_photo_path="reference-photos/s2/p.jpg",
        )


# ---- enrollment failure reason (BP7b) ---------------------------------


async def test_successful_enroll_has_no_failure_reason() -> None:
    svc, _, _, _ = _svc()  # default FakeMlClient stores 1 embedding
    student = await _create(
        svc, school_id=_S1, name="A", email="a@x.io", reference_photo_path=_PATH,
    )
    assert student.enrollment_status is EnrollmentStatus.ENROLLED
    assert student.enrollment_failure_reason is None


async def test_no_face_failure_records_reason() -> None:
    ml = FakeMlClient(embeddings_stored=0, photo_status="no_face")
    svc, _, _, _ = _svc(ml_client=ml)
    student = await _create(
        svc, school_id=_S1, name="A", email="a@x.io", reference_photo_path=_PATH,
    )
    assert student.enrollment_status is EnrollmentStatus.FAILED
    assert student.enrollment_failure_reason is EnrollmentFailureReason.NO_FACE


async def test_processing_error_failure_records_generic_error_reason() -> None:
    # Any 0-embedding per-photo status that isn't "no_face" is a generic processing error.
    ml = FakeMlClient(embeddings_stored=0, photo_status="error")
    svc, _, _, _ = _svc(ml_client=ml)
    student = await _create(
        svc, school_id=_S1, name="A", email="a@x.io", reference_photo_path=_PATH,
    )
    assert student.enrollment_status is EnrollmentStatus.FAILED
    assert student.enrollment_failure_reason is EnrollmentFailureReason.ERROR


async def test_multiple_faces_with_zero_embeddings_maps_to_generic_error() -> None:
    # Defensive contract pin: the ML normally enrolls the largest face (so multiple_faces
    # yields an embedding and never fails); if it ever reports 0, we fall through to the
    # generic ERROR reason rather than a misleading no_face.
    ml = FakeMlClient(embeddings_stored=0, photo_status="multiple_faces")
    svc, _, _, _ = _svc(ml_client=ml)
    student = await _create(
        svc, school_id=_S1, name="A", email="a@x.io", reference_photo_path=_PATH,
    )
    assert student.enrollment_status is EnrollmentStatus.FAILED
    assert student.enrollment_failure_reason is EnrollmentFailureReason.ERROR


async def test_ml_outage_records_unavailable_reason() -> None:
    # A transport failure (ML down / the ReadTimeout we hit in the wild) is transient.
    ml = FakeMlClient(raise_on_enroll=UpstreamError("read timeout"))
    svc, _, _, _ = _svc(ml_client=ml)
    student = await _create(
        svc, school_id=_S1, name="A", email="a@x.io", reference_photo_path=_PATH,
    )
    assert student.enrollment_status is EnrollmentStatus.FAILED
    assert student.enrollment_failure_reason is EnrollmentFailureReason.ML_UNAVAILABLE


async def test_successful_reenroll_clears_the_failure_reason() -> None:
    # A prior failure reason must not linger once enrollment succeeds (BP7b).
    ml = FakeMlClient(embeddings_stored=0, photo_status="no_face")
    svc, strepo, _, _ = _svc(ml_client=ml)
    created = await _create(
        svc, school_id=_S1, name="A", email="a@x.io", reference_photo_path=_PATH,
    )
    assert created.enrollment_failure_reason is EnrollmentFailureReason.NO_FACE

    ml._embeddings = 1  # a better photo / retry now succeeds
    ml._photo_status = "enrolled"
    refreshed = await svc.enroll_student(school_id=_S1, student_id=created.id)
    assert refreshed.enrollment_status is EnrollmentStatus.ENROLLED
    assert refreshed.enrollment_failure_reason is None
    # And it's cleared in the store, not just the returned copy.
    stored = await strepo.get(_S1, created.id)
    assert stored is not None and stored.enrollment_failure_reason is None


async def test_reload_read_miss_falls_back_to_computed_status() -> None:
    # If the post-write re-read misses (row vanished), the returned Student still
    # reflects the enrollment status just computed (via _reload's fallback).
    svc, strepo, _, _ = _svc()

    async def _miss(school_id: str, student_id: str) -> None:
        return None

    strepo.get = _miss  # force the read-miss branch
    student = await _create(
        svc, school_id=_S1, name="M", email="m@x.io", reference_photo_path=_PATH,
    )
    assert student.enrollment_status is EnrollmentStatus.ENROLLED


# ---- reads + tenant isolation -----------------------------------------


async def test_get_student_is_tenant_scoped() -> None:
    svc, _, _, _ = _svc(schools=[make_school(id=_S1), make_school(id="s2")])
    student = await _create(
        svc, school_id=_S1, name="T", email="t@x.io", reference_photo_path=_PATH,
    )
    # Another school cannot fetch it.
    with pytest.raises(NotFoundError):
        await svc.get_student(school_id="s2", student_id=student.id)


async def test_list_students_returns_only_own_school() -> None:
    svc, _, _, _ = _svc(schools=[make_school(id=_S1), make_school(id="s2")])
    await svc.create_student(
        school_id=_S1, name="A", email="a@x.io", reference_photo_path=_PATH,
    )
    await svc.create_student(
        school_id="s2", name="B", email="b@x.io",
        reference_photo_path="reference-photos/s2/p.jpg",
    )
    assert {s.name for s in await svc.list_students(school_id=_S1)} == {"A"}


# ---- delete ------------------------------------------------------------


async def test_delete_removes_ml_login_and_profile() -> None:
    svc, strepo, urepo, ml = _svc()
    student = await _create(
        svc, school_id=_S1, name="D", email="d@x.io", reference_photo_path=_PATH,
    )
    await svc.delete_student(school_id=_S1, student_id=student.id)
    assert ml.delete_calls == [(_S1, student.id)]
    assert await urepo.get(student.user_id) is None  # login gone
    assert await strepo.get(_S1, student.id) is None  # profile cascaded


async def test_delete_missing_student_raises_before_ml_call() -> None:
    svc, _, _, ml = _svc()
    with pytest.raises(NotFoundError):
        await svc.delete_student(school_id=_S1, student_id="ghost")
    assert ml.delete_calls == []


async def test_delete_keeps_local_rows_when_ml_delete_fails() -> None:
    # ML delete must succeed before we remove local rows / the storage object, so we never
    # orphan embeddings; on failure everything stays for a retry (0026). ML is deleted FIRST,
    # so a failure means the object was NOT touched.
    store = FakeObjectStore()
    svc, strepo, urepo, _ = _svc(
        ml_client=FakeMlClient(raise_on_delete=UpstreamError("ml down")),
        object_store=store,
    )
    student = await _create(
        svc, school_id=_S1, name="K", email="k@x.io", reference_photo_path=_PATH,
    )
    with pytest.raises(UpstreamError):
        await svc.delete_student(school_id=_S1, student_id=student.id)
    assert await urepo.get(student.user_id) is not None
    assert await strepo.get(_S1, student.id) is not None
    assert store.delete_attempts == 0  # ML-first: the object is untouched on ML failure


# ---- BP8e: erasure of the reference-photo object (decisions/0053) -------


async def test_delete_erases_reference_photo_object() -> None:
    store = FakeObjectStore()
    svc, _, urepo, _ = _svc(object_store=store)
    student = await _create(
        svc, school_id=_S1, name="E", email="e@x.io", reference_photo_path=_PATH,
    )
    await svc.delete_student(school_id=_S1, student_id=student.id)
    assert store.deleted == [_PATH]  # the storage object was removed
    assert await urepo.get(student.user_id) is None  # + the login gone


async def test_delete_storage_failure_retries_then_best_effort() -> None:
    # A failing storage delete is retried, then swallowed (best-effort) — the erasure
    # still completes; a leaked object is a storage cost, not a DB/privacy hole.
    store = FakeObjectStore(fail_deletes=True)
    svc, strepo, urepo, _ = _svc(object_store=store)
    student = await _create(
        svc, school_id=_S1, name="R", email="r@x.io", reference_photo_path=_PATH,
    )
    await svc.delete_student(school_id=_S1, student_id=student.id)  # does NOT raise
    assert store.delete_attempts == 3  # bounded retry
    assert await urepo.get(student.user_id) is None  # student still fully deleted
    assert await strepo.get(_S1, student.id) is None


async def test_delete_photoless_student_skips_object_delete() -> None:
    # A bulk-imported (photoless) student has no object to erase, but ML delete still fires
    # (its embeddings/matches/detections may exist from a since-cleared photo).
    store = FakeObjectStore()
    svc, _, urepo, ml = _svc(object_store=store)
    student = await _create(
        svc, school_id=_S1, name="P", email="p@x.io", reference_photo_path=None,
    )
    await svc.delete_student(school_id=_S1, student_id=student.id)
    assert store.delete_attempts == 0
    assert ml.delete_calls == [(_S1, student.id)]  # ML footprint still purged
    assert await urepo.get(student.user_id) is None
