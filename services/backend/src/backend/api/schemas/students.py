"""Student API schemas (decisions/0026).

Request/response shapes for the student routes. The reference photo is uploaded by
the frontend directly to Supabase via a backend-minted signed URL; the create request
carries only the returned object path (never bytes). Responses expose the student
profile, never the linked login's password hash.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from backend.domain.models import EnrollmentStatus, Student
from backend.services.listing_service import StudentListing

# argon2 has no input cap (0024) — bound provisioning passwords at the edge.
_MAX_PASSWORD_LEN = 1024


class CreateStudentRequest(BaseModel):
    """Create a student + login with a caller-set temp password (0026)."""

    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=_MAX_PASSWORD_LEN)
    # The bucket-relative object path returned by POST /v1/students/upload-url.
    reference_photo_path: str = Field(min_length=1, max_length=1024)


class UploadUrlResponse(BaseModel):
    upload_url: str
    object_path: str
    max_upload_mb: int


class StudentResponse(BaseModel):
    id: str
    school_id: str
    name: str
    email: str  # the student's login email (decisions/0033)
    reference_photo_path: str
    enrollment_status: EnrollmentStatus
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
            created_at=student.created_at,
            updated_at=student.updated_at,
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
