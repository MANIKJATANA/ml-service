"""Student API schemas (decisions/0026).

Request/response shapes for the student routes. The reference photo is uploaded by
the frontend directly to Supabase via a backend-minted signed URL; the create request
carries only the returned object path (never bytes). Responses expose the student
profile, never the linked login's password hash.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from backend.domain.models import EnrollmentFailureReason, EnrollmentStatus, Student
from backend.services.listing_service import StudentListing
from backend.services.pagination import Page
from backend.services.student_service import BulkStudentResult, ProvisionedStudent

# The largest batch one CSV import can create in a single request (BP7d).
_MAX_BULK_ROWS = 500


class CreateStudentRequest(BaseModel):
    """Create a student (BP7d): the temp password is generated server-side + returned
    once; the reference photo is **optional** — omit it and the student is created
    ``pending`` (a photo can be added later to enroll)."""

    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    # The bucket-relative object path returned by POST /v1/students/upload-url; null to
    # create a photoless (pending) student.
    reference_photo_path: str | None = Field(default=None, min_length=1, max_length=1024)


class SetReferencePhotoRequest(BaseModel):
    """Set/replace a student's reference photo, then re-enroll (BP7d-2). Carries only the
    object path from POST /v1/students/upload-url (the bytes never hit the backend)."""

    reference_photo_path: str = Field(min_length=1, max_length=1024)


class BulkStudentRow(BaseModel):
    """One CSV row (BP7d). Raw strings — validated per row in the service so one bad row
    doesn't reject the whole import; only the lengths are capped here (abuse guard)."""

    name: str = Field(max_length=1000)
    email: str = Field(max_length=1000)


class BulkImportRequest(BaseModel):
    students: list[BulkStudentRow] = Field(min_length=1, max_length=_MAX_BULK_ROWS)


class UploadUrlResponse(BaseModel):
    upload_url: str
    object_path: str
    max_upload_mb: int


class StudentResponse(BaseModel):
    id: str
    school_id: str
    name: str
    email: str  # the student's login email (decisions/0033)
    reference_photo_path: str | None  # null for a photoless (bulk-imported) student (BP7d)
    enrollment_status: EnrollmentStatus
    # Why enrollment failed, when it did (BP7b); null otherwise. The FE maps it to a
    # specific explanation + fix.
    enrollment_failure_reason: EnrollmentFailureReason | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_student(cls, student: Student) -> StudentResponse:
        return cls(
            id=student.id,
            school_id=student.school_id,
            name=student.name,
            email=student.email,
            reference_photo_path=student.reference_photo_path,
            enrollment_status=student.enrollment_status,
            enrollment_failure_reason=student.enrollment_failure_reason,
            created_at=student.created_at,
            updated_at=student.updated_at,
        )


class ProvisionedStudentResponse(BaseModel):
    """A newly created student + its ONE-TIME server-generated temp password (BP7d).

    Returned by ``POST /v1/students`` — the plaintext is shown once so staff can hand it
    to the student; only its hash is stored. `enroll` / `GET` keep the leaner
    ``StudentResponse`` (no password)."""

    student: StudentResponse
    temp_password: str

    @classmethod
    def from_provisioned(cls, p: ProvisionedStudent) -> ProvisionedStudentResponse:
        return cls(
            student=StudentResponse.from_student(p.student),
            temp_password=p.temp_password,
        )


class BulkStudentResultResponse(BaseModel):
    """One row's outcome from a bulk import (BP7d). ``status`` ∈ {created, duplicate,
    invalid, error}; ``temp_password`` set only when ``created``."""

    name: str
    email: str
    status: str
    temp_password: str | None = None
    student_id: str | None = None
    error: str | None = None

    @classmethod
    def from_result(cls, r: BulkStudentResult) -> BulkStudentResultResponse:
        return cls(
            name=r.name,
            email=r.email,
            status=r.status,
            temp_password=r.temp_password,
            student_id=r.student_id,
            error=r.error,
        )


class BulkImportResponse(BaseModel):
    results: list[BulkStudentResultResponse]

    @classmethod
    def from_results(cls, results: list[BulkStudentResult]) -> BulkImportResponse:
        return cls(results=[BulkStudentResultResponse.from_result(r) for r in results])


class StudentListItem(StudentResponse):
    """A students-list row: the student + how many photos/events they appear in (BP2).
    The single-item GET/POST/enroll keep the leaner ``StudentResponse``."""

    appearance_count: int
    event_count: int

    @classmethod
    def from_listing(cls, listing: StudentListing) -> StudentListItem:
        return cls(
            **StudentResponse.from_student(listing.student).model_dump(),
            appearance_count=listing.appearance_count,
            event_count=listing.event_count,
        )


class StudentListPageResponse(BaseModel):
    """One page of the students list (BP9) + the unpaginated total for the given filter."""

    items: list[StudentListItem]
    total: int
    limit: int
    offset: int

    @classmethod
    def from_page(cls, page: Page[StudentListing]) -> StudentListPageResponse:
        return cls(
            items=[StudentListItem.from_listing(x) for x in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )
