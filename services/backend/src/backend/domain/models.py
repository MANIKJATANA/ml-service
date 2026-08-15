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


class EnrollmentFailureReason(StrEnum):
    """Why an enrollment ``failed`` — a small, closed set the FE maps to a specific
    explanation + fix (BP7b, decisions/0045). Set only when ``enrollment_status`` is
    ``failed``; ``None`` otherwise (a success clears it)."""

    NO_FACE = "no_face"  # no face detected in the reference photo -> use a clearer one
    ML_UNAVAILABLE = "ml_unavailable"  # ML service unreachable/timed out -> retry
    ERROR = "error"  # the photo couldn't be processed (corrupt/unsupported) -> replace


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
    """Per-photo status, a column on the backend ``media`` row (decisions/0027, BP8a). The
    **ML worker** flips it ``pending -> completed`` as it finishes each photo (or
    ``-> failed`` when it can't process one), and reads it to skip only ``completed`` photos
    on a redistribute — so a ``failed`` photo is **re-attempted** on the next Process."""

    PENDING = "pending"  # uploaded; not yet processed by ML
    COMPLETED = "completed"  # ML finished processing this photo
    FAILED = "failed"  # ML couldn't process it (corrupt/undecodable/error) — retryable


class MediaVariant(StrEnum):
    """Which rendition of an image a caller wants (BP17, image thumbnails). ``thumb`` asks
    for the stored downscaled sibling (the backend-generated copy made at register/create);
    ``full`` is the original. ``thumb`` falls back to full-res when no thumbnail is stored
    (pre-BP17 rows + video)."""

    THUMB = "thumb"
    FULL = "full"


class SortDir(StrEnum):
    """List sort direction (BP9, decisions/0055)."""

    ASC = "asc"
    DESC = "desc"


# Per-endpoint list sort keys (BP9, decisions/0055). Each enum is the full allow-set for
# one list endpoint (used as the API Query type → a bad value 422s for free) and names both
# **row-native** columns (sorted in SQL, via ``list_page``) and **count columns** (sorted
# across the whole list in-Python off a school-wide aggregate + ``list_ids``, so the isolated
# ML ``matches`` seam is never SQL-joined — see ``ListingService``). The ``*_COUNT_SORTS``
# frozensets below mark which members take the count path.


class StudentSort(StrEnum):
    NAME = "name"
    CREATED_AT = "created_at"
    APPEARANCE_COUNT = "appearance_count"  # count column
    EVENT_COUNT = "event_count"  # count column


class EventSort(StrEnum):
    EVENT_DATE = "event_date"
    NAME = "name"
    CREATED_AT = "created_at"
    MEDIA_COUNT = "media_count"  # count column
    MATCHED_STUDENTS = "matched_students"  # count column
    NEEDS_REVIEW = "needs_review"  # count column


class UserSort(StrEnum):
    """Staff/admin rows are ``users`` — no ``name`` column, so email is the only text sort."""

    EMAIL = "email"
    CREATED_AT = "created_at"


class SchoolSort(StrEnum):
    NAME = "name"
    CREATED_AT = "created_at"
    STUDENTS = "students"  # count column
    EVENTS = "events"  # count column
    TEACHERS = "teachers"  # count column
    ADMINS = "admins"  # count column


# The count-column members of each sort enum (the ones that take the in-Python global-sort
# path). Row-native members (the complement) are sorted directly in SQL.
STUDENT_COUNT_SORTS: frozenset[StudentSort] = frozenset(
    {StudentSort.APPEARANCE_COUNT, StudentSort.EVENT_COUNT}
)
EVENT_COUNT_SORTS: frozenset[EventSort] = frozenset(
    {EventSort.MEDIA_COUNT, EventSort.MATCHED_STUDENTS, EventSort.NEEDS_REVIEW}
)
SCHOOL_COUNT_SORTS: frozenset[SchoolSort] = frozenset(
    {SchoolSort.STUDENTS, SchoolSort.EVENTS, SchoolSort.TEACHERS, SchoolSort.ADMINS}
)


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
    # Bumped on every password change/reset (BP18d); the token's `tv` claim is compared to
    # this on each request + refresh, so a changed/reset password revokes all older sessions.
    token_version: int = 0


@dataclass(frozen=True, slots=True)
class Student:
    """A student profile (decisions/0026). ``id`` (as a string) is the ML
    ``student_id``; ``user_id`` links the login account created alongside it."""

    id: str
    school_id: str
    user_id: str
    name: str
    email: str  # the linked login's email — denormalized onto the read model (0033)
    # Nullable (BP7d): a bulk-imported student has no reference photo yet (pending).
    reference_photo_path: str | None
    enrollment_status: EnrollmentStatus
    created_at: datetime
    updated_at: datetime
    # Why enrollment failed, when it did (BP7b) — else None. Populated from the ML
    # per-photo result / the transport failure; cleared on a successful (re-)enroll.
    enrollment_failure_reason: EnrollmentFailureReason | None = None
    # BP17: a stored downscaled sibling of reference_photo_path for the staff avatar (None
    # for a photoless student + pre-BP17 rows). ML enrollment reads reference_photo_path.
    reference_photo_thumbnail_path: str | None = None
    # BP11a: the class/section this student belongs to (nullable — an un-classed student).
    # ``student_group_name`` is denormalized onto the read model for list display (like email).
    student_group_id: str | None = None
    student_group_name: str | None = None
    # BP18d: the linked login's status (active/disabled) — denormalized off the users JOIN
    # (like email). Lets staff show + toggle a student's non-destructive login kill-switch.
    status: UserStatus = UserStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class StudentGroup:
    """A class / section — the organizing unit for students (BP11a, decisions/0058).

    Tenant-owned (``school_id``). ``name`` is the human label (e.g. "Grade 3B"); ``grade``/
    ``section`` are optional filter labels (e.g. "3", "B"). A student points at one group via
    ``students.student_group_id`` (nullable) — deleting a group un-assigns its students
    (SET NULL), never deletes them. Bounded per school (a few dozen)."""

    id: str
    school_id: str
    name: str
    grade: str | None
    section: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class StudentGroupListing:
    """A class + its member count for the classes list (BP11a). Composed from a grouped
    ``students`` count keyed by ``student_group_id`` — the pure services never issue SQL."""

    group: StudentGroup
    student_count: int


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


# The categories a school starts with (BP11b, decisions/0059) — seeded on school-create + into
# every existing school in migration 0014. Stored as tenant rows, so a school can add/remove more.
DEFAULT_EVENT_CATEGORIES: tuple[str, ...] = (
    "Sports",
    "Academic",
    "Arts",
    "Trip",
    "Ceremony",
    "Other",
)


@dataclass(frozen=True, slots=True)
class EventCategory:
    """A tenant-owned event category (BP11b, decisions/0059). A school starts with the
    ``DEFAULT_EVENT_CATEGORIES`` (seeded on create) and admins/staff can add more; an event points
    at one via ``events.category_id`` (nullable) — deleting a category un-tags its events (SET
    NULL), never deletes them. Bounded per school."""

    id: str
    school_id: str
    name: str
    created_at: datetime
    updated_at: datetime


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
    # BP4 distribution (decisions/0041): auto_notify = announce to students on completion
    # (a live gate); notified_at = last manual "Notify students" push (set-forward).
    auto_notify: bool
    notified_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # BP11b: a free-text term + the event's category (a tenant-owned event_categories row).
    # ``category_name`` is denormalized for display (like ``student_group_name``); null = none.
    term: str | None = None
    category_id: str | None = None
    category_name: str | None = None
    # BP11c: the class this event belongs to (nullable — an untagged, school-wide event).
    # SET NULL on class delete. ``student_group_name`` is denormalized via a LEFT JOIN for
    # display (like ``category_name``); a teacher's "focus" scope reads the tag.
    student_group_id: str | None = None
    student_group_name: str | None = None


@dataclass(frozen=True, slots=True)
class NotificationEvent:
    """The context handed to each notification channel (BP4, decisions/0041).

    Immutable + channel-agnostic so a future email/WhatsApp channel needs no service
    change. ``contact`` is the student's reachable address (email today) — resolved at
    send time; the ``log`` channel never logs it (PII)."""

    school_id: str
    student_id: str
    student_name: str
    contact: str
    event_id: str
    event_name: str
    event_date: date | None
    media_count: int


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
    # BP17: a stored downscaled sibling of storage_path for gallery-tile previews. Null for
    # pre-BP17 media and — by FE convention, not a backend invariant — video (which keeps a
    # browser poster). The ML pipeline always reads storage_path (the full-res).
    thumbnail_path: str | None = None


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
class EventMatchCounts:
    """Per-event match rollup for the events list (BP2). Derived from ``matches`` in one
    grouped query: distinct students who appear + how many of the event's matches are
    flagged for review."""

    matched_students: int
    needs_review: int


@dataclass(frozen=True, slots=True)
class StudentAppearanceCounts:
    """Per-student appearance rollup for the students list (BP2). One grouped ``matches``
    query: total appearances (photos the student is in) + distinct events."""

    appearance_count: int
    event_count: int


@dataclass(frozen=True, slots=True)
class SchoolRollup:
    """Per-school rollup for the platform schools list/detail (BP2). Composed from batch
    grouped counts over users/students/events — one query each, no per-school fan-out."""

    admins: int
    teachers: int
    students: int
    events: int


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


class MatchVerdict(StrEnum):
    """A staff/student correction over the ML ``matches`` (BP5, decisions/0042). Keyed on
    the stable ``(media_id, student_id)`` pair — the backend never writes ML tables."""

    CONFIRMED = "confirmed"  # a real ML match staff vouched for (stands)
    REJECTED = "rejected"  # "this isn't the right person" — hidden from the student
    ADDED = "added"  # report-a-miss: staff added a student the ML missed


@dataclass(frozen=True, slots=True)
class MatchCorrection:
    """One correction row over a ``(media, student)`` pair (BP5, decisions/0042).

    The overlay: a ``rejected`` pair is removed from the effective appearances (+ download
    blocked); an ``added`` pair is unioned in (no ML confidence); ``confirmed`` stands.
    ``resolves_review`` is true when the corrected match was ``needs_review`` at review time
    (drives the dashboard's unresolved-review count)."""

    media_id: str
    student_id: str
    event_id: str
    verdict: MatchVerdict
    resolves_review: bool


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    """The outcome of one rate-limit check (BP8c, decisions/0051). ``retry_after_s`` is
    meaningful only when not ``allowed`` — how many seconds until the window resets."""

    allowed: bool
    retry_after_s: int


@dataclass(frozen=True, slots=True)
class DownloadAuditEntry:
    """One recorded media download — the trust audit (BP8b, decisions/0050).

    Append-only: the backend writes a row every time an entitled caller mints a signed
    download URL. ``actor_role`` is the caller's role denormalized at write time (so the
    log still shows *who* even after the account is deleted → ``actor_user_id`` becomes
    None). ``subject_student_id`` is set only for a student's own self-download (the
    student they are), None for staff. Display data (actor email, event/student names) is
    joined from the backend's own rows by ``AuditService`` — never stored here."""

    id: str
    school_id: str
    media_id: str
    event_id: str
    actor_user_id: str | None
    actor_role: str
    subject_student_id: str | None
    created_at: datetime
