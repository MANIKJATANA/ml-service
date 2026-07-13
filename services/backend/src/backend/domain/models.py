"""Backend domain models — pure, frozen value types (no third-party imports).

Ids are ``str`` (canonical UUID strings); the DB stores them as ``uuid`` and the
repositories convert on read (decisions/0023). The string form is exactly what the
ML service receives, so no conversion happens at the ML boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
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


class EventStatus(StrEnum):
    """Event lifecycle (independent of processing). v1 archives, never deletes."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class EventProcessingStatus(StrEnum):
    """The single event-level status the FE reads in one DB call (decisions/0027).

    The backend sets ``queued`` on Process; the **ML worker** flips it to ``processing``
    on pickup and ``completed`` when the whole event is done. The backend never derives
    it from per-photo rows."""

    NOT_STARTED = "not_started"  # media may be uploaded, but Process not pressed yet
    QUEUED = "queued"  # backend enqueued the event job; ML hasn't picked it up
    PROCESSING = "processing"  # ML picked the event up and is working through its photos
    COMPLETED = "completed"  # ML finished every photo in the event


class MediaType(StrEnum):
    """Kind of media. Values match the ML service's ``MediaType`` verbatim
    (decisions/0027)."""

    IMAGE = "image"
    VIDEO = "video"


class MediaProcessingStatus(StrEnum):
    """Per-photo status, a column on the backend ``media`` row (decisions/0027). The
    **ML worker** flips it ``pending -> completed`` as it finishes each photo, and reads
    it to skip photos already done on a redistribute. A photo that never finishes just
    stays ``pending``."""

    PENDING = "pending"  # uploaded; not yet processed by ML
    COMPLETED = "completed"  # ML finished processing this photo


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
    email: str  # the linked login's email — denormalized onto the read model (0033)
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
class SignedDownload:
    """A short-lived signed URL to fetch a stored object (decisions/0028).

    The backend mints this on demand for an entitled caller; the bytes are fetched
    straight from storage, never proxied through the backend."""

    download_url: str
    expires_in_s: int


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


@dataclass(frozen=True, slots=True)
class Event:
    """An event whose media is distributed to appearing students (decisions/0027).
    ``id`` (as a string) is the ML ``event_id`` (``matches.event_id``).

    ``status`` is the lifecycle (active/archived); ``processing_status`` is the
    event-level inference state the FE polls."""

    id: str
    school_id: str
    name: str
    description: str | None
    event_date: date | None
    created_by: str | None
    status: EventStatus
    processing_status: EventProcessingStatus
    enqueued_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Media:
    """One uploaded event photo + its per-photo processing state (decisions/0027).
    ``id`` (as a string) is the ML ``media_id``; ``storage_path`` is the ML ``media_uri``.
    Recording a photo enqueues nothing — processing is event-level (see ``EventJob``)."""

    id: str
    school_id: str
    event_id: str
    storage_path: str
    media_type: MediaType
    processing_status: MediaProcessingStatus
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class EventJob:
    """The exact payload enqueued for the ML inference worker (decisions/0027).

    One job per **event** (not per photo). These two fields are XADD'd as strings onto
    the shared Redis stream; the field names are a binding contract with the ML worker —
    do not rename without changing both sides. The ML worker reads the backend ``media``
    roster for the event from the shared DB to learn which photos to process."""

    school_id: str
    event_id: str


@dataclass(frozen=True, slots=True)
class EventRollup:
    """A school's events counted by lifecycle + inference state (BP1 dashboard).

    ``processing`` is the count of events currently in flight (``processing_status`` in
    ``{queued, processing}``) — a live "N events distributing" signal. Derived from one
    grouped query in the adapter; the pure services never issue SQL."""

    total: int
    active: int
    archived: int
    processing: int


@dataclass(frozen=True, slots=True)
class Appearance:
    """One ``matches`` row: a student who appears in a media (decisions/0028).

    The join keys the galleries fan out on plus the two decision facts they surface
    (``confidence``, ``needs_review``). Read-only — the ML service writes ``matches``;
    the backend only reads it (via ``MlResultsReader``). Display data (names, dates,
    photo metadata) is joined from the backend's own rows, never from here."""

    student_id: str
    media_id: str
    event_id: str
    confidence: float
    needs_review: bool
