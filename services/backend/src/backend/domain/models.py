"""Backend domain models — pure, frozen value types (no third-party imports).

Ids are ``str`` (canonical UUID strings); the DB stores them as ``uuid`` and the
repositories convert on read (decisions/0023). The string form is exactly what the
ML service receives, so no conversion happens at the ML boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Role(StrEnum):
    PLATFORM_ADMIN = "platform_admin"
    SCHOOL_ADMIN = "school_admin"
    TEACHER = "teacher"
    STUDENT = "student"


class SchoolStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class EnrollmentStatus(StrEnum):
    PENDING = "pending"  # student created; ML enrollment not yet confirmed
    ENROLLED = "enrolled"  # ML stored >= 1 embedding for the reference photo
    FAILED = "failed"  # enroll attempted but stored 0 embeddings / ML unreachable


@dataclass(frozen=True, slots=True)
class School:
    id: str
    name: str
    max_teachers: int
    status: SchoolStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class User:
    id: str
    school_id: str | None  # None -> platform_admin (global, no tenant)
    email: str
    password_hash: str
    role: Role
    status: UserStatus
    # True for staff-provisioned / temp-password accounts until they set their own
    # password on first login (decisions/0024). login surfaces it; change-password
    # clears it.
    must_change_password: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Student:
    """A student profile (decisions/0026). ``id`` (as a string) is the ML
    ``student_id``; ``user_id`` links the login account created alongside it."""

    id: str
    school_id: str
    user_id: str
    name: str
    reference_photo_path: str
    enrollment_status: EnrollmentStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SignedUpload:
    """A short-lived, direct-to-storage upload target (decisions/0026).

    The backend mints this; the frontend uploads the reference photo straight to
    ``upload_url`` (never through the backend) and later submits ``object_path``.
    """

    upload_url: str
    object_path: str
    token: str | None = None


@dataclass(frozen=True, slots=True)
class PhotoResult:
    """Per-photo enrollment outcome as reported by the ML service (FR-E4)."""

    index: int
    status: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class EnrollmentOutcome:
    """The ML enrollment API's result for one student (decisions/0009)."""

    embeddings_stored: int
    photo_results: tuple[PhotoResult, ...]
