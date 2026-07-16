"""Student use-cases — create + ML enrollment (decisions/0026).

Depends only on ports (no HTTP, no RBAC): authorization is enforced at the route via
`require_permissions(student:manage)` and the tenant is the caller's token `school_id`,
never the URL/body. Creating a student provisions a login (`role=student`, temp
password, `must_change_password=true`) alongside the profile and triggers synchronous
ML enrollment; the result is recorded as `enrollment_status`. ML availability never
blocks account creation — a failed/unreachable enroll is a recorded, retryable state.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

import structlog

from backend.domain.emails import validate_email
from backend.domain.errors import ConflictError, NotFoundError, ValidationError
from backend.domain.models import (
    EnrollmentFailureReason,
    EnrollmentOutcome,
    EnrollmentStatus,
    Role,
    School,
    SchoolStatus,
    SignedUpload,
    Student,
)
from backend.domain.ports import (
    MlEnrollmentClient,
    ObjectStore,
    PasswordHasher,
    SchoolRepository,
    StudentRepository,
    UserRepository,
)
from backend.services.credentials import generate_temp_password

_MAX_NAME_LEN = 200
_log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ProvisionedStudent:
    """A newly created student + its one-time server-generated temp password (BP7d)."""

    student: Student
    temp_password: str


@dataclass(frozen=True, slots=True)
class BulkStudentResult:
    """One row's outcome from a bulk import (BP7d). ``status`` ∈ {created, duplicate,
    invalid, error}; ``temp_password``/``student_id`` set only when ``created``."""

    name: str
    email: str
    status: str
    temp_password: str | None = None
    student_id: str | None = None
    error: str | None = None

# The per-photo status the ML reports when it found no face (ml_service
# PhotoStatus.NO_FACE.value). A cross-service string contract: the backend must not import
# from ml_service (layering), so the literal is pinned here and its mapping is test-covered
# (test_student_service.py). Any other 0-embedding status maps to the generic ERROR.
_ML_STATUS_NO_FACE = "no_face"


class StudentService:
    def __init__(
        self,
        students: StudentRepository,
        users: UserRepository,
        schools: SchoolRepository,
        hasher: PasswordHasher,
        object_store: ObjectStore,
        ml_client: MlEnrollmentClient,
        *,
        reference_photo_prefix: str,
    ) -> None:
        self._students = students
        self._users = users
        self._schools = schools
        self._hasher = hasher
        self._object_store = object_store
        self._ml = ml_client
        self._prefix = reference_photo_prefix.strip("/")

    # ---- reference-photo upload URL ------------------------------------

    def _tenant_prefix(self, school_id: str) -> str:
        return f"{self._prefix}/{school_id}/"

    async def create_upload_url(self, *, school_id: str) -> SignedUpload:
        """Mint a signed upload target under the caller's tenant prefix.

        The object key embeds the token's `school_id`, so a caller can only ever
        upload within their own tenant's prefix.
        """
        object_path = f"{self._tenant_prefix(school_id)}{uuid.uuid4()}"
        return await self._object_store.create_signed_upload_url(object_path)

    # ---- create + enroll ------------------------------------------------

    async def create_student(
        self,
        *,
        school_id: str,
        name: str,
        email: str,
        reference_photo_path: str | None = None,
    ) -> ProvisionedStudent:
        """Create a student (+ login with a server-generated temp password, BP7d) and, if
        a reference photo was given, enroll it. With no photo the student is created
        ``pending`` (a bulk-style single create); a photo can be added later to enroll."""
        clean_name = _clean_name(name)
        await self._require_active_school(school_id)
        if reference_photo_path is not None:
            self._require_tenant_photo_path(school_id, reference_photo_path)

        prov = await self._provision_student(
            school_id=school_id,
            name=clean_name,
            email=email,
            reference_photo_path=reference_photo_path,
        )
        if reference_photo_path is None:  # photoless -> stays pending, no ML call
            return prov

        status, reason = await self._run_enroll(
            school_id=school_id,
            student_id=prov.student.id,
            reference_photo_path=reference_photo_path,
        )
        student = await self._reload(
            school_id, prov.student.id, fallback=prov.student, status=status, reason=reason
        )
        return ProvisionedStudent(student, prov.temp_password)

    async def bulk_create_students(
        self, *, school_id: str, rows: list[tuple[str, str]]
    ) -> list[BulkStudentResult]:
        """Create many students from ``(name, email)`` pairs (BP7d CSV import). Best-effort
        per row — a bad/duplicate row is recorded and the batch continues. Every student is
        created **photoless** (``pending``); photos are added later. The active-school
        check is a **snapshot** taken once up front (a mid-batch suspension isn't
        re-checked — the same accepted single-admin-sequential-writes race as the teacher
        cap). Each created row carries its one-time temp password."""
        await self._require_active_school(school_id)
        results: list[BulkStudentResult] = []
        for name, email in rows:
            try:
                clean_name = _clean_name(name)
                clean_email = validate_email(email)  # per-row; never aborts the batch
                prov = await self._provision_student(
                    school_id=school_id,
                    name=clean_name,
                    email=clean_email,
                    reference_photo_path=None,
                )
                results.append(
                    BulkStudentResult(
                        name=name,
                        email=email,
                        status="created",
                        temp_password=prov.temp_password,
                        student_id=prov.student.id,
                    )
                )
            except ConflictError:
                results.append(BulkStudentResult(name, email, "duplicate"))
            except ValidationError as exc:
                results.append(BulkStudentResult(name, email, "invalid", error=str(exc)))
            except Exception:  # noqa: BLE001 — isolate one row's failure from the batch
                _log.error("bulk_student_create_failed", email=email, exc_info=True)
                results.append(BulkStudentResult(name, email, "error"))
        return results

    async def enroll_student(self, *, school_id: str, student_id: str) -> Student:
        """Re-enroll / retry using the student's stored reference photo (0026)."""
        student = await self.get_student(school_id=school_id, student_id=student_id)
        if student.reference_photo_path is None:
            # A bulk-imported student has no photo yet (BP7d) — nothing to enroll.
            raise ValidationError("student has no reference photo to enroll")
        status, reason = await self._run_enroll(
            school_id=school_id,
            student_id=student.id,
            reference_photo_path=student.reference_photo_path,
        )
        return await self._reload(
            school_id, student.id, fallback=student, status=status, reason=reason
        )

    async def _require_active_school(self, school_id: str) -> School:
        school = await self._schools.get(school_id)
        if school is None:
            # school_id is token-derived (tenant_of), not a client path param — a missing
            # school is anomalous invalid state, not a 404. ValidationError (400).
            raise ValidationError("school not found")
        if school.status is not SchoolStatus.ACTIVE:
            raise ValidationError("school is suspended")
        return school

    def _require_tenant_photo_path(self, school_id: str, reference_photo_path: str) -> None:
        # Path guard: only a key this school was handed an upload URL for. Stops a caller
        # submitting another tenant's / an arbitrary object path.
        if not reference_photo_path.startswith(self._tenant_prefix(school_id)):
            raise ValidationError("reference_photo_path is outside this school's prefix")

    async def _provision_student(
        self,
        *,
        school_id: str,
        name: str,
        email: str,
        reference_photo_path: str | None,
    ) -> ProvisionedStudent:
        """The two writes (no shared UoW): create the login first with a server-generated
        temp password (a duplicate email raises ConflictError with nothing else written),
        then the profile; compensate a profile-insert failure by deleting the orphan login
        (0026, BP7d). No enrollment here — the caller decides."""
        temp_password = generate_temp_password()
        user = await self._users.create(
            school_id=school_id,
            email=email,
            password_hash=self._hasher.hash(temp_password),
            role=Role.STUDENT,
            must_change_password=True,
        )
        try:
            student = await self._students.create(
                school_id=school_id,
                user_id=user.id,
                name=name,
                reference_photo_path=reference_photo_path,
            )
        except Exception:
            # Compensating action — remove the orphan login. Its own failure must NOT mask
            # the original profile-insert error (which we re-raise).
            try:
                await self._users.delete(user.id)
            except Exception:
                _log.error("compensating_delete_failed", user_id=user.id, exc_info=True)
            raise
        return ProvisionedStudent(student, temp_password)

    async def _run_enroll(
        self, *, school_id: str, student_id: str, reference_photo_path: str
    ) -> tuple[EnrollmentStatus, EnrollmentFailureReason | None]:
        """Enroll the student's photo and persist the resulting status (+ reason on fail).

        Best-effort: an ML outage is caught and recorded as `failed`, so account
        creation is never blocked by ML availability (0026). On failure the reason is
        captured (BP7b) so staff get a specific explanation; on success it's None (which
        clears any prior reason).
        """
        reason: EnrollmentFailureReason | None = None
        try:
            outcome = await self._ml.enroll(
                school_id=school_id,
                student_id=student_id,
                photo_uris=[reference_photo_path],
            )
            if outcome.embeddings_stored >= 1:
                status = EnrollmentStatus.ENROLLED
            else:
                status = EnrollmentStatus.FAILED
                reason = _reason_from_outcome(outcome)
        except Exception:
            # UpstreamError (ML down / timed out) or any enroll failure — record + move
            # on. A transport failure is transient, so surface it as "try again" (BP7b).
            _log.warning("ml_enroll_failed", student_id=student_id, exc_info=True)
            status = EnrollmentStatus.FAILED
            reason = EnrollmentFailureReason.ML_UNAVAILABLE
        # Persist best-effort: a status-write failure must not fail an already-created
        # account (0026's "enrollment never blocks account creation"). On failure the
        # row keeps its prior status; a re-enroll can fix it, and the caller's response
        # reflects the actually-persisted state (via _reload's re-read).
        try:
            await self._students.set_enrollment(
                student_id, status=status, failure_reason=reason
            )
        except Exception:
            _log.error("set_enrollment_failed", student_id=student_id, exc_info=True)
        return status, reason

    # ---- reads ----------------------------------------------------------

    async def get_student(self, *, school_id: str, student_id: str) -> Student:
        student = await self._students.get(school_id, student_id)
        if student is None:
            raise NotFoundError(f"student not found: {student_id}")
        return student

    async def list_students(self, *, school_id: str) -> list[Student]:
        return await self._students.list_by_school(school_id)

    # ---- delete (FR-E2) -------------------------------------------------

    async def delete_student(self, *, school_id: str, student_id: str) -> None:
        student = await self.get_student(school_id=school_id, student_id=student_id)
        # ML delete FIRST — must succeed so we never orphan embeddings; if the ML
        # service is down the UpstreamError surfaces (502) and the operator retries.
        await self._ml.delete(school_id=school_id, student_id=student.id)
        # Deleting the login row cascades the profile away (students.user_id FK).
        await self._users.delete(student.user_id)

    async def _reload(
        self,
        school_id: str,
        student_id: str,
        *,
        fallback: Student,
        status: EnrollmentStatus,
        reason: EnrollmentFailureReason | None,
    ) -> Student:
        fresh = await self._students.get(school_id, student_id)
        if fresh is not None:
            return fresh
        # The row was just written/updated; if a read misses, reflect the persisted
        # status + failure reason (BP7b) so the response matches what was stored.
        return replace(
            fallback, enrollment_status=status, enrollment_failure_reason=reason
        )


def _clean_name(name: str) -> str:
    clean = name.strip()
    if not clean or len(clean) > _MAX_NAME_LEN:
        raise ValidationError("student name must be 1-200 characters")
    return clean


def _reason_from_outcome(outcome: EnrollmentOutcome) -> EnrollmentFailureReason:
    """Map a 0-embedding ML enroll result to a failure reason (BP7b).

    A single reference photo is sent, so the first per-photo result is decisive: the ML
    reports ``no_face`` when it detected none; anything else that stored no embedding
    (a per-photo ``error``, or an unexpected status) is a generic processing ``error``.
    (``multiple_faces`` never lands here — the ML enrolls the largest face.)
    """
    first = outcome.photo_results[0] if outcome.photo_results else None
    if first is not None and first.status == _ML_STATUS_NO_FACE:
        return EnrollmentFailureReason.NO_FACE
    return EnrollmentFailureReason.ERROR
