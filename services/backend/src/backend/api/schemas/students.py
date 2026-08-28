"""Student API schemas (decisions/0026).

Request/response shapes for the student routes. The reference photo is uploaded by
the frontend directly to Supabase via a backend-minted signed URL; the create request
carries only the returned object path (never bytes). Responses expose the student
profile, never the linked login's password hash.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, StringConstraints

from backend.domain.models import (
    EnrollmentFailureReason,
    EnrollmentStatus,
    SignedUpload,
    Student,
    UserStatus,
)
from backend.services.engagement_service import StudentEngagement
from backend.services.listing_service import StudentListing
from backend.services.pagination import Page
from backend.services.student_service import (
    BulkStudentResult,
    ProvisionedStudent,
    ResolvedPhotoTarget,
)
from backend.settings import settings

# The largest batch one CSV import can create in a single request (BP7d).
_MAX_BULK_ROWS = 500


class CreateStudentRequest(BaseModel):
    """Create a student (BP7d): the temp password is generated server-side + returned
    once; the reference photo is **optional** — omit it and the student is created
    ``pending`` (a photo can be added later to enroll)."""

    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    # The bucket-relative object path returned by POST /v1/students/upload-url; null to
    # create a photoless (pending) student. BP17: the backend generates the display thumbnail
    # from this object — the caller never supplies a thumbnail path.
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
    """A minted upload target. The FE PUTs the original to ``upload_url`` and submits the
    ``object_path`` on register/create; the backend generates the BP17 thumbnail itself."""

    upload_url: str
    object_path: str
    max_upload_mb: int

    @classmethod
    def from_signed(cls, signed: SignedUpload, *, max_upload_mb: int) -> UploadUrlResponse:
        return cls(
            upload_url=signed.upload_url,
            object_path=signed.object_path,
            max_upload_mb=max_upload_mb,
        )


class StudentResponse(BaseModel):
    id: str
    school_id: str
    name: str
    email: str  # the student's login email (decisions/0033)
    reference_photo_path: str | None  # null for a photoless (bulk-imported) student (BP7d)
    # BP17: the backend-generated display thumbnail (null when photoless / video / generation
    # failed). The FE requests ?size=thumb only when this is set, else the full-res photo.
    reference_photo_thumbnail_path: str | None = None
    enrollment_status: EnrollmentStatus
    # Why enrollment failed, when it did (BP7b); null otherwise. The FE maps it to a
    # specific explanation + fix.
    enrollment_failure_reason: EnrollmentFailureReason | None = None
    # BP11a: the class this student belongs to (null = un-classed). ``student_group_name`` is
    # denormalized for list/detail display; the FE shows a class badge + drives the filter.
    student_group_id: str | None = None
    student_group_name: str | None = None
    # BP18d: the linked login's status (active/disabled). Staff show + toggle a student's
    # non-destructive login kill-switch; a disabled student can't sign in but keeps all history.
    status: UserStatus = UserStatus.ACTIVE
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
            reference_photo_thumbnail_path=student.reference_photo_thumbnail_path,
            enrollment_status=student.enrollment_status,
            enrollment_failure_reason=student.enrollment_failure_reason,
            student_group_id=student.student_group_id,
            student_group_name=student.student_group_name,
            status=student.status,
            created_at=student.created_at,
            updated_at=student.updated_at,
        )


class UpdateStudentRequest(BaseModel):
    """Set (or clear) a student's class (BP11a). ``student_group_id`` is required-but-nullable
    — send a class id to assign, ``null`` to un-assign (an empty body is a 422, never a silent
    un-assign). A foreign/unknown class → 404."""

    student_group_id: str | None = Field(max_length=64)


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


# A photo filename the FE sends for bulk-photo matching (BP10). Length-capped (abuse guard);
# the per-batch count is capped at the configurable ``bulk_photo_max_files`` below (→ 422).
_PhotoFilename = Annotated[str, StringConstraints(min_length=1, max_length=1024)]


class MatchPhotosRequest(BaseModel):
    """Filenames the FE wants mapped to students for bulk-photo enrollment (BP10). The batch
    is capped at the configurable ``bulk_photo_max_files`` — an over-size list is a 422.

    The cap is bound at import (mirroring ``api/pagination.py``'s page-size ``Query`` bounds),
    so it reflects ``BE_BULK_PHOTO_MAX_FILES`` at process start — not a per-request change."""

    filenames: list[_PhotoFilename] = Field(
        min_length=1, max_length=settings.bulk_photo_max_files
    )


class PhotoMatchResult(BaseModel):
    """One filename's match (BP10): the student it maps to, or ``matched=false``."""

    filename: str
    matched: bool
    student_id: str | None = None
    student_name: str | None = None
    enrollment_status: EnrollmentStatus | None = None

    @classmethod
    def from_target(cls, t: ResolvedPhotoTarget) -> PhotoMatchResult:
        s = t.student
        return cls(
            filename=t.filename,
            matched=s is not None,
            student_id=s.id if s is not None else None,
            student_name=s.name if s is not None else None,
            enrollment_status=s.enrollment_status if s is not None else None,
        )


class MatchPhotosResponse(BaseModel):
    results: list[PhotoMatchResult]

    @classmethod
    def from_targets(cls, targets: list[ResolvedPhotoTarget]) -> MatchPhotosResponse:
        return cls(results=[PhotoMatchResult.from_target(t) for t in targets])


class StudentEngagementResponse(BaseModel):
    """One student's reach + engagement (BP23) — its own read so ``StudentResponse`` stays
    a cheap write-path projection. Powers the student-detail "Engagement" card."""

    events_appearing: int
    photos_appearing: int
    events_opened: int
    last_opened_at: datetime | None
    downloads: int

    @classmethod
    def from_engagement(cls, e: StudentEngagement) -> StudentEngagementResponse:
        return cls(
            events_appearing=e.events_appearing,
            photos_appearing=e.photos_appearing,
            events_opened=e.events_opened,
            last_opened_at=e.last_opened_at,
            downloads=e.downloads,
        )


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
