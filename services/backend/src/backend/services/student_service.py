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
from dataclasses import replace

import structlog

from backend.domain.errors import NotFoundError, ValidationError
from backend.domain.models import (
    EnrollmentStatus,
    Role,
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

_MAX_NAME_LEN = 200
_log = structlog.get_logger(__name__)


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
        password: str,
        reference_photo_path: str,
    ) -> Student:
        clean_name = name.strip()
        if not clean_name or len(clean_name) > _MAX_NAME_LEN:
            raise ValidationError("student name must be 1-200 characters")

        school = await self._schools.get(school_id)
        if school is None:
            # school_id is token-derived (tenant_of), not a client path param — a
            # missing school is anomalous invalid state, not a "resource not found"
            # 404. ValidationError (400), matching the suspended branch below.
            raise ValidationError("school not found")
        if school.status is not SchoolStatus.ACTIVE:
            raise ValidationError("school is suspended")

        # Path guard: only a key this school was handed an upload URL for. Stops a
        # caller submitting another tenant's / an arbitrary object path.
        if not reference_photo_path.startswith(self._tenant_prefix(school_id)):
            raise ValidationError("reference_photo_path is outside this school's prefix")

        # Two writes, no shared UoW: create the login first (a duplicate email
        # raises ConflictError with nothing else written), then the profile;
        # compensate a profile-insert failure by deleting the orphan login (0026).
        user = await self._users.create(
            school_id=school_id,
            email=email,
            password_hash=self._hasher.hash(password),
            role=Role.STUDENT,
            must_change_password=True,
        )
        try:
            student = await self._students.create(
                school_id=school_id,
                user_id=user.id,
                name=clean_name,
                reference_photo_path=reference_photo_path,
            )
        except Exception:
            # Compensating action — remove the orphan login. Its own failure must
            # NOT mask the original profile-insert error (which we re-raise).
            try:
                await self._users.delete(user.id)
            except Exception:
                _log.error("compensating_delete_failed", user_id=user.id, exc_info=True)
            raise

        status = await self._run_enroll(
            school_id=school_id,
            student_id=student.id,
            reference_photo_path=reference_photo_path,
        )
        return await self._reload(school_id, student.id, fallback=student, status=status)

    async def enroll_student(self, *, school_id: str, student_id: str) -> Student:
        """Re-enroll / retry using the student's stored reference photo (0026)."""
        student = await self.get_student(school_id=school_id, student_id=student_id)
        status = await self._run_enroll(
            school_id=school_id,
            student_id=student.id,
            reference_photo_path=student.reference_photo_path,
        )
        return await self._reload(school_id, student.id, fallback=student, status=status)

    async def _run_enroll(
        self, *, school_id: str, student_id: str, reference_photo_path: str
    ) -> EnrollmentStatus:
        """Enroll the student's photo and persist the resulting status.

        Best-effort: an ML outage is caught and recorded as `failed`, so account
        creation is never blocked by ML availability (0026).
        """
        try:
            outcome = await self._ml.enroll(
                school_id=school_id,
                student_id=student_id,
                photo_uris=[reference_photo_path],
            )
            status = (
                EnrollmentStatus.ENROLLED
                if outcome.embeddings_stored >= 1
                else EnrollmentStatus.FAILED
            )
        except Exception:
            # UpstreamError (ML down) or any enroll failure — record + move on.
            _log.warning("ml_enroll_failed", student_id=student_id, exc_info=True)
            status = EnrollmentStatus.FAILED
        # Persist best-effort: a status-write failure must not fail an already-created
        # account (0026's "enrollment never blocks account creation"). On failure the
        # row keeps its prior status; a re-enroll can fix it, and the caller's response
        # reflects the actually-persisted state (via _reload's re-read).
        try:
            await self._students.set_enrollment(student_id, status=status)
        except Exception:
            _log.error("set_enrollment_failed", student_id=student_id, exc_info=True)
        return status

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
    ) -> Student:
        fresh = await self._students.get(school_id, student_id)
        if fresh is not None:
            return fresh
        # The row was just written/updated; if a read misses, reflect the status.
        return replace(fallback, enrollment_status=status)
