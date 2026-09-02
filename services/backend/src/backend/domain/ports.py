"""Backend ports — the Protocol interfaces the services depend on.

Concrete implementations live under ``adapters/`` and are selected by config via
``wiring/registry.py`` (decisions/0022). Keeping services import-pure against these
Protocols (no SQLAlchemy/httpx/redis/supabase) is enforced by
``tests/test_layering.py``. The surface grows per phase; Phase 5 adds the event and
media repositories, the job producer, and the ML results reader (decisions/0027).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Protocol

from backend.domain.models import (
    UNSET,
    AdminActionAuditEntry,
    Appearance,
    DownloadAuditEntry,
    EnrollmentFailureReason,
    EnrollmentOutcome,
    EnrollmentStatus,
    Event,
    EventCategory,
    EventJob,
    EventMatchCounts,
    EventProcessingStatus,
    EventRollup,
    EventSort,
    EventStatus,
    MatchCorrection,
    MatchVerdict,
    Media,
    MediaProcessingStatus,
    MediaType,
    NotificationEvent,
    PlatformConfig,
    RateLimitResult,
    Role,
    School,
    SchoolSort,
    SchoolStatus,
    SchoolWhatsAppConfig,
    SignedUpload,
    StoredObject,
    Student,
    StudentAppearanceCounts,
    StudentGroup,
    StudentSort,
    UnsetType,
    User,
    UserSort,
    UserStatus,
    WhatsAppReceipt,
    WhatsAppSendLogEntry,
)
from backend.domain.permissions import Permission
from backend.domain.tokens import TokenClaims, TokenPair, TokenType


class SchoolRepository(Protocol):
    async def create(self, *, name: str, max_teachers: int) -> School: ...
    async def get(self, school_id: str) -> School | None: ...
    async def list_all(self) -> list[School]: ...
    async def list_page(
        self,
        *,
        limit: int,
        offset: int,
        q: str | None = None,
        sort: SchoolSort = SchoolSort.NAME,
        descending: bool = False,
    ) -> list[School]:
        """One page of the platform schools list (BP9). Row-native ``sort`` only; the rollup
        count sorts (students/events/teachers/admins) take the id-scan path (``list_ids``)."""
        ...
    async def count_page(self, *, q: str | None = None) -> int: ...
    async def list_ids(self, *, q: str | None = None) -> list[str]: ...
    async def list_by_ids(self, school_ids: Sequence[str]) -> list[School]:
        """Bulk-load schools by id (BP9 count-sort page hydration). Platform-wide (no
        tenant); malformed ids are dropped. Order not guaranteed."""
        ...
    async def update(
        self,
        school_id: str,
        *,
        name: str | None = None,
        max_teachers: int | None = None,
        status: SchoolStatus | None = None,
    ) -> School | None:
        """Update a school's mutable fields (BP18c) — only the provided (non-None) fields
        change. Returns the updated School, or None if no such school."""
        ...


class UserRepository(Protocol):
    async def create(
        self,
        *,
        school_id: str | None,
        email: str,
        password_hash: str,
        role: Role,
        must_change_password: bool = False,
    ) -> User: ...
    async def get(self, user_id: str) -> User | None: ...
    async def get_by_email(self, email: str) -> User | None: ...
    async def set_password(
        self,
        user_id: str,
        *,
        password_hash: str,
        must_change_password: bool,
        revoke_sessions: bool = True,
    ) -> None:
        """Set a user's password hash. ``revoke_sessions`` (default True) bumps
        ``token_version`` so all older tokens are rejected (BP18d) — pass False only for a
        transparent rehash where the password is unchanged."""
        ...
    async def set_status(self, user_id: str, *, status: UserStatus) -> None: ...
    async def touch_last_login(self, user_id: str) -> None:
        """Stamp ``last_login_at = now()`` on a successful login (BP14). Best-effort; not
        called on token refresh (not an interactive sign-in)."""
        ...
    async def count_by_school_and_role(self, school_id: str, role: Role) -> int: ...
    async def count_active_by_school_and_role(
        self, school_id: str, role: Role
    ) -> int:
        """Count only ``active`` users of a role in a school (BP18b last-admin guard) —
        distinct from ``count_by_school_and_role``, which counts regardless of status."""
        ...
    async def count_signed_in_by_school_and_role(
        self, school_id: str, role: Role
    ) -> int:
        """Users of a role in a school who have ever signed in (``last_login_at`` set) —
        the school analytics sign-in rate numerator (BP14). Tenant-scoped."""
        ...
    async def signed_in_role_counts_by_school(self) -> dict[str, dict[Role, int]]:
        """The signed-in sibling of ``role_counts_by_school`` — per (school, role) count of
        users with ``last_login_at`` set (BP14 estate funnel). Cross-tenant (``school:manage``
        only); platform admins (null school) excluded."""
        ...
    async def list_by_school_and_role(
        self, school_id: str, role: Role
    ) -> list[User]: ...
    async def list_page_by_role(
        self,
        school_id: str,
        role: Role,
        *,
        limit: int,
        offset: int,
        q: str | None = None,
        sort: UserSort = UserSort.CREATED_AT,
        descending: bool = True,
    ) -> list[User]:
        """One page of a school's users of one role — staff (teacher) + admin rosters (BP9).
        Searched on email (users have no name column) + sorted in SQL. No count sorts."""
        ...
    async def count_page_by_role(
        self, school_id: str, role: Role, *, q: str | None = None
    ) -> int: ...
    async def role_counts_by_school(self) -> dict[str, dict[Role, int]]: ...
    async def delete(self, user_id: str) -> None: ...


class StudentRepository(Protocol):
    """Backend-owned students. Reads are tenant-scoped: a ``student_id`` that
    belongs to another school resolves to ``None`` (decisions/0026)."""

    async def create(
        self,
        *,
        school_id: str,
        user_id: str,
        name: str,
        reference_photo_path: str | None = None,
        reference_photo_thumbnail_path: str | None = None,
        mobile_number: str | None = None,
        whatsapp_opt_in: bool = False,
    ) -> Student: ...
    async def get(self, school_id: str, student_id: str) -> Student | None: ...
    async def get_by_user_id(
        self, school_id: str, user_id: str
    ) -> Student | None: ...
    async def list_by_school(self, school_id: str) -> list[Student]: ...
    async def list_page(
        self,
        school_id: str,
        *,
        limit: int,
        offset: int,
        q: str | None = None,
        sort: StudentSort = StudentSort.NAME,
        descending: bool = False,
        status: EnrollmentStatus | None = None,
        student_group_id: str | None = None,
        scope_group_ids: Sequence[str] | None = None,
        never_signed_in: bool = False,
        never_opened: bool = False,
    ) -> list[Student]:
        """One page of the students list (BP9), searched/filtered/sorted in SQL. Only
        row-native ``sort`` members reach here; count-column sorts take the id-scan path
        (``list_ids``). BP11a: ``student_group_id`` filters to one class. BP11c:
        ``scope_group_ids`` limits results to that set of classes — a teacher's "focus"
        scope (``None`` = no scope; ``[]`` = a teacher with no classes = no students). BP23:
        ``never_signed_in``/``never_opened`` filter to students who never signed in / never
        opened a distribution (same-schema — never the ML seam)."""
        ...
    async def count_page(
        self,
        school_id: str,
        *,
        q: str | None = None,
        status: EnrollmentStatus | None = None,
        student_group_id: str | None = None,
        scope_group_ids: Sequence[str] | None = None,
        never_signed_in: bool = False,
        never_opened: bool = False,
    ) -> int:
        """Total students matching the same ``q``/``status``/class filter + focus scope +
        BP23 activity filters (the page's ``total``)."""
        ...
    async def list_ids(
        self,
        school_id: str,
        *,
        q: str | None = None,
        status: EnrollmentStatus | None = None,
        student_group_id: str | None = None,
        scope_group_ids: Sequence[str] | None = None,
        never_signed_in: bool = False,
        never_opened: bool = False,
    ) -> list[str]:
        """All matching student ids (id-only, no join) — the count-sort path fetches these,
        sorts them by a school-wide count dict in-Python, then hydrates one page via
        ``list_by_ids`` (BP9). Bounded by the tenant slice; never loads full rows."""
        ...
    async def list_by_ids(
        self, school_id: str, student_ids: Sequence[str]
    ) -> list[Student]:
        """Bulk-load students by id within one tenant (BP9 galleries + count-sort). Order
        is not guaranteed; callers that need the input order re-order in-Python."""
        ...
    async def resolve_by_emails(
        self, school_id: str, emails: Sequence[str]
    ) -> list[Student]:
        """Students in this school whose login email matches one of ``emails``
        (case-insensitive) — BP10 bulk-photo filename→student matching. Tenant-scoped; order
        not guaranteed. The email set is bounded by the route's per-batch cap."""
        ...
    async def enrollment_counts(
        self, school_id: str
    ) -> dict[EnrollmentStatus, int]: ...
    async def counts_by_school(self) -> dict[str, int]: ...
    async def enrolled_counts_by_school(self) -> dict[str, int]:
        """Successfully-enrolled student count per school (BP14 estate funnel) — the
        cross-tenant, enrolled-only sibling of ``counts_by_school``. Cross-tenant
        (``school:manage`` only)."""
        ...
    async def set_enrollment(
        self,
        student_id: str,
        *,
        status: EnrollmentStatus,
        failure_reason: EnrollmentFailureReason | None = None,
    ) -> None: ...
    async def set_reference_photo(
        self,
        student_id: str,
        *,
        reference_photo_path: str,
        reference_photo_thumbnail_path: str | None = None,
    ) -> None: ...
    async def set_group(
        self, student_id: str, *, student_group_id: str | None
    ) -> None:
        """Assign one student to a class, or clear it with ``None`` (BP11a). The service
        validates a non-null ``student_group_id`` names a class in the same school first."""
        ...
    async def set_group_bulk(
        self,
        school_id: str,
        *,
        student_group_id: str,
        student_ids: Sequence[str],
    ) -> int:
        """Assign many of one school's students to a class (BP11a); returns the count
        updated. Tenant-scoped — a foreign id is silently skipped."""
        ...
    async def set_mobile(
        self, student_id: str, *, mobile_number: str | None, whatsapp_opt_in: bool
    ) -> None:
        """Set/clear the WhatsApp contact number + opt-in for one student (Phase 0); raises
        ``NotFoundError`` on an unknown id. The service resolves tenancy via a school-scoped
        ``get`` BEFORE calling — this write is not itself tenant-scoped."""
        ...


class StudentGroupRepository(Protocol):
    """Backend-owned classes/sections (BP11a, decisions/0058). Reads are tenant-scoped: a
    ``group_id`` from another school resolves to ``None``. Bounded per school (a few dozen),
    so the list is unpaginated."""

    async def create(
        self, *, school_id: str, name: str, grade: str | None, section: str | None
    ) -> StudentGroup: ...
    async def get(self, school_id: str, group_id: str) -> StudentGroup | None: ...
    async def list_by_school(self, school_id: str) -> list[StudentGroup]: ...
    async def update(
        self,
        school_id: str,
        group_id: str,
        *,
        name: str,
        grade: str | None,
        section: str | None,
    ) -> StudentGroup | None:
        """Replace a class's editable fields (name/grade/section). Returns ``None`` if the
        class is absent/foreign (the service maps that to 404)."""
        ...
    async def delete(self, school_id: str, group_id: str) -> bool:
        """Delete a class (its students are un-assigned via ``ON DELETE SET NULL``). Returns
        ``False`` if the class is absent/foreign (→ 404)."""
        ...
    async def student_counts(self, school_id: str) -> dict[str, int]:
        """Per-class member count for one school (the classes list). One grouped scan over
        ``students.student_group_id``; classes with zero members are absent (caller
        zero-fills)."""
        ...


class EventRepository(Protocol):
    """Backend-owned events. Reads are tenant-scoped: an ``event_id`` from another
    school resolves to ``None`` (decisions/0027). ``set_processing`` is only used to set
    ``queued`` on Process — the ML worker owns the ``processing``/``completed`` writes."""

    async def create(
        self,
        *,
        school_id: str,
        name: str,
        description: str | None,
        event_date: date | None,
        created_by: str | None,
        category_id: str | None = None,
        term: str | None = None,
        student_group_id: str | None = None,
    ) -> Event: ...
    async def get(self, school_id: str, event_id: str) -> Event | None: ...
    async def list_by_school(self, school_id: str) -> list[Event]: ...
    async def list_page(
        self,
        school_id: str,
        *,
        limit: int,
        offset: int,
        q: str | None = None,
        sort: EventSort = EventSort.EVENT_DATE,
        descending: bool = True,
        status: EventStatus | None = None,
        category_id: str | None = None,
        term: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        student_group_id: str | None = None,
        scope_group_ids: Sequence[str] | None = None,
    ) -> list[Event]:
        """One page of the events list (BP9). Row-native ``sort`` only; count sorts →
        ``list_ids`` (see ``StudentRepository.list_page``). BP11b: ``category_id``/``term`` filter
        + ``date_from``/``date_to`` bound ``event_date`` (the calendar's month window). BP11c:
        ``student_group_id`` filters to one class; ``scope_group_ids`` is a teacher's "focus"
        scope — events tagged to those classes OR untagged/school-wide (``None`` = no scope)."""
        ...
    async def count_page(
        self,
        school_id: str,
        *,
        q: str | None = None,
        status: EventStatus | None = None,
        category_id: str | None = None,
        term: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        student_group_id: str | None = None,
        scope_group_ids: Sequence[str] | None = None,
    ) -> int: ...
    async def list_ids(
        self,
        school_id: str,
        *,
        q: str | None = None,
        status: EventStatus | None = None,
        category_id: str | None = None,
        term: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        student_group_id: str | None = None,
        scope_group_ids: Sequence[str] | None = None,
    ) -> list[str]: ...
    async def list_terms(self, school_id: str) -> list[str]:
        """Distinct non-null ``term`` values for a school, sorted (BP11b — the FE term filter)."""
        ...
    async def list_by_ids(
        self, school_id: str, event_ids: Sequence[str]
    ) -> list[Event]: ...
    async def status_counts(self, school_id: str) -> EventRollup: ...
    # BP19c: active, not-in-flight events with >=1 pending photo (the dashboard "photos to
    # process" alert — widened from never-processed-only to catch a second batch too).
    async def count_active_with_pending_media(self, school_id: str) -> int: ...
    async def count_distributed(self, school_id: str) -> int: ...
    async def counts_by_school(self) -> dict[str, int]: ...
    async def distributed_counts_by_school(self) -> dict[str, int]:
        """Announced-events count per school (BP14 estate funnel) — the cross-tenant sibling
        of ``count_distributed``. Cross-tenant (``school:manage`` only)."""
        ...
    async def recent_event_counts_by_school(
        self, since: datetime
    ) -> dict[str, int]:
        """Events created at/after ``since`` per school (BP14 stalled-school heuristic).
        Cross-tenant (``school:manage`` only)."""
        ...
    async def first_distributed_at_by_school(self) -> dict[str, datetime]:
        """Earliest announce time per school (BP23 estate — days-to-first-delivery), =
        ``min(coalesce(notified_at, completed_at))`` under the announced predicate. One grouped
        scan, cross-tenant (``school:manage`` only); a never-announced school is absent."""
        ...
    async def last_event_created_at_by_school(self) -> dict[str, datetime]:
        """Most recent event ``created_at`` per school (BP23 estate — the "no event since …"
        idle anchor). One grouped MAX scan, cross-tenant (``school:manage`` only); a school
        with no events is absent."""
        ...
    async def monthly_event_date_counts(self, school_id: str) -> dict[str, int]:
        """Events per calendar month by their ``event_date`` (BP14 trend — when the event
        happened, not when the row was created), keyed ``'YYYY-MM'``. Undated events are
        excluded (they have no month). One grouped scan, tenant-scoped."""
        ...
    async def update(
        self,
        school_id: str,
        event_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        event_date: date | None = None,
        status: EventStatus | None = None,
        auto_notify: bool | None = None,
        category_id: str | None | UnsetType = UNSET,
        term: str | None | UnsetType = UNSET,
        student_group_id: str | None | UnsetType = UNSET,
    ) -> Event | None:
        """Partial update. BP24 (decisions/0079) makes the three **tag** fields
        (``category_id``/``term``/``student_group_id``) tri-state: ``UNSET`` = leave unchanged,
        an explicit ``None`` = **clear** to null, a value = set (revising 0027's "None =
        unchanged" for these three only). The other fields keep ``None`` = unchanged."""
        ...
    async def set_status_bulk(
        self, school_id: str, event_ids: Sequence[str], *, status: EventStatus
    ) -> int:
        """Set the lifecycle ``status`` (active/archived) on many of one school's events in one
        tenant-scoped UPDATE (BP13 bulk archive/restore). A foreign/malformed id is silently
        skipped (``WHERE school_id AND id IN (…)``); returns the count updated."""
        ...
    async def set_processing(
        self, event_id: str, *, status: EventProcessingStatus
    ) -> None: ...
    async def mark_notified(self, event_id: str) -> None: ...


class EventCategoryRepository(Protocol):
    """Backend-owned, tenant-configurable event categories (BP11b, decisions/0059). Reads are
    tenant-scoped: a ``category_id`` from another school resolves to ``None``. Bounded per school,
    so the list is unpaginated. Seeded with the defaults on school-create."""

    async def create(self, *, school_id: str, name: str) -> EventCategory: ...
    async def get(self, school_id: str, category_id: str) -> EventCategory | None: ...
    async def get_by_name(
        self, school_id: str, name: str
    ) -> EventCategory | None:
        """Case-insensitive lookup by name within a school — for the add-dedupe guard."""
        ...
    async def list_by_school(self, school_id: str) -> list[EventCategory]: ...
    async def delete(self, school_id: str, category_id: str) -> bool:
        """Delete a category (its events are un-tagged via ``ON DELETE SET NULL``). Returns
        ``False`` if the category is absent/foreign (→ 404)."""
        ...
    async def seed_defaults(self, school_id: str, names: Sequence[str]) -> None:
        """Insert the default categories for a new school, skipping any that already exist
        (idempotent on the ``(school_id, name)`` unique)."""
        ...


class TeacherClassRepository(Protocol):
    """Backend-owned teacher ↔ class delegation links (BP11c, decisions/0060). A teacher can
    own several classes; a class can have several teachers (many-to-many). Every read/write is
    tenant-scoped by ``school_id``; ids are returned (the service composes the classes/teachers
    from the group + user repos, both bounded per school)."""

    async def add(
        self, *, school_id: str, teacher_user_id: str, student_group_id: str
    ) -> None:
        """Link one teacher to one class (idempotent — a duplicate ``(teacher, class)`` is a
        no-op). The service validates both are in-school + the target is a teacher first."""
        ...
    async def remove(
        self, *, school_id: str, teacher_user_id: str, student_group_id: str
    ) -> bool:
        """Unlink one teacher from one class. Returns ``False`` if no such link (→ 404)."""
        ...
    async def replace_for_teacher(
        self, *, school_id: str, teacher_user_id: str, student_group_ids: Sequence[str]
    ) -> None:
        """Set a teacher's whole class set (the staff-side "Edit classes" PUT). Tenant-scoped:
        a foreign class id is skipped. Replaces the teacher's existing links atomically."""
        ...
    async def list_group_ids_for_teacher(
        self, school_id: str, teacher_user_id: str
    ) -> list[str]:
        """The class ids one teacher is linked to (their focus scope + "my classes")."""
        ...
    async def list_teacher_ids_for_group(
        self, school_id: str, student_group_id: str
    ) -> list[str]:
        """The teacher user ids linked to one class (the class-detail teacher roster)."""
        ...


class MediaRepository(Protocol):
    """Backend-owned event photos. Reads are tenant-scoped (decisions/0027). Recording a
    photo enqueues nothing; the per-photo status column is written by the ML worker
    directly (shared DB), so this repo only reads it."""

    async def create(
        self,
        *,
        school_id: str,
        event_id: str,
        storage_path: str,
        media_type: MediaType,
        thumbnail_path: str | None = None,
        uploaded_by: str | None = None,
    ) -> Media: ...
    async def get(self, school_id: str, media_id: str) -> Media | None: ...
    async def list_by_event(self, school_id: str, event_id: str) -> list[Media]: ...
    async def list_page_by_event(
        self,
        school_id: str,
        event_id: str,
        *,
        limit: int,
        offset: int,
        status: MediaProcessingStatus | None = None,
    ) -> list[Media]:
        """One page of an event's media (BP9), newest-upload-agnostic ``created_at`` order
        with an optional status filter. Media has no text/count sort — just pagination."""
        ...
    async def count_page_by_event(
        self,
        school_id: str,
        event_id: str,
        *,
        status: MediaProcessingStatus | None = None,
    ) -> int: ...
    async def list_by_ids(
        self, school_id: str, media_ids: Sequence[str]
    ) -> list[Media]: ...
    async def status_counts(
        self, school_id: str, event_id: str
    ) -> dict[MediaProcessingStatus, int]: ...
    async def school_status_counts(
        self, school_id: str
    ) -> dict[MediaProcessingStatus, int]: ...
    async def counts_by_event(self, school_id: str) -> dict[str, int]: ...
    # BP19c: still-`pending` photos per event — lets the list flag a "second batch".
    async def pending_counts_by_event(self, school_id: str) -> dict[str, int]: ...
    async def monthly_upload_counts(self, school_id: str) -> dict[str, int]:
        """Photos/videos uploaded per calendar month for a school (BP14 trend), keyed
        ``'YYYY-MM'`` (UTC ``date_trunc`` of ``created_at``). One grouped scan, tenant-scoped."""
        ...


class EventJobProducer(Protocol):
    """Enqueues one ML inference job per **event** (decisions/0027). Raises
    ``UpstreamError`` when the queue backend is unreachable."""

    async def enqueue(self, job: EventJob) -> None: ...


class ObjectStore(Protocol):
    """Mints direct-to-storage signed URLs; the *original* bytes never transit the backend.

    Upload: the frontend uploads to the signed URL and later submits the object path
    (decisions/0026). Download: the backend mints a short-lived read URL for an entitled
    caller (decisions/0028). The BP17 thumbnail path (``download_bytes``/``upload_bytes``,
    decisions/0056) is the one exception — the backend reads a just-uploaded image and writes
    its downscaled sibling. Raises ``UpstreamError`` when the store is unreachable."""

    async def create_signed_upload_url(self, object_path: str) -> SignedUpload: ...
    async def create_signed_download_url(
        self, object_path: str, *, expires_in_s: int
    ) -> str: ...
    async def delete(self, object_path: str) -> None:
        """Delete one stored object (BP8e erasure, decisions/0053). Idempotent — a missing
        object is not an error. Raises ``UpstreamError`` when the store is unreachable, so
        the caller can retry (a failed delete leaves an orphaned object, never a bad row)."""
        ...

    async def download_bytes(self, object_path: str) -> bytes:
        """Read one stored object's bytes (BP17 thumbnail generation, decisions/0056). Raises
        ``UpstreamError`` when the store is unreachable or the object is missing."""
        ...

    async def upload_bytes(
        self, object_path: str, data: bytes, *, content_type: str
    ) -> None:
        """Write bytes to one object key, overwriting (BP17 thumbnail, decisions/0056). Raises
        ``UpstreamError`` when the store is unreachable."""
        ...

    async def list_prefix(self, prefix: str) -> list[StoredObject]:
        """List every object under ``prefix``, recursively, each with its ``last_modified``
        timestamp (W3a WhatsApp-variant reaper). Keys are ``{prefix}/{school_id}/{media_id}.jpg``
        — two levels deep — so an implementation must descend, not stop at the prefix folder. An
        empty/missing prefix yields ``[]``. Raises ``UpstreamError`` when the store is
        unreachable."""
        ...


class Thumbnailer(Protocol):
    """Downscales an image to a small preview (BP17, decisions/0056). The one place image
    bytes are decoded in the backend — kept behind this port so ``domain``/``services`` stay
    free of image libraries (the concrete Pillow adapter is the only importer)."""

    async def make_thumbnail(
        self, data: bytes, *, max_edge: int | None = None, quality: int | None = None
    ) -> bytes | None:
        """Return a small JPEG of ``data``, or ``None`` if it can't be produced (a non-image,
        a decode/encode error) — best-effort, so a bad image never fails the upload.

        W1: ``max_edge``/``quality`` optionally override the instance config for one call (the
        WhatsApp send variant targets a larger size/quality than the BP17 tile thumbnail — a
        smaller re-encode, NOT a hard byte cap); when omitted the instance values apply, so
        every existing caller is unchanged."""
        ...


class MlEnrollmentClient(Protocol):
    """The backend's only outbound call to the ML service (decisions/0009).

    Synchronous enroll/refresh + delete of a student's embeddings. Raises
    ``UpstreamError`` when the ML service is unreachable or errors."""

    async def enroll(
        self, *, school_id: str, student_id: str, photo_uris: list[str]
    ) -> EnrollmentOutcome: ...
    async def delete(self, *, school_id: str, student_id: str) -> None: ...


class MlResultsReader(Protocol):
    """Read-only reader over the ML-owned ``matches`` table (decisions/0028).

    The single backend coupling to the ML result schema: it reads *who appears in what*
    and returns pure ``Appearance`` join-keys + decision facts; all display data is
    joined from backend-owned rows. Every read is tenant-scoped by ``school_id``. A
    Phase-7 ``information_schema`` contract test guards the consumed columns."""

    async def list_event_appearances(
        self, school_id: str, event_id: str
    ) -> list[Appearance]: ...
    async def list_student_appearances(
        self, school_id: str, student_id: str
    ) -> list[Appearance]: ...
    async def list_media_appearances(
        self, school_id: str, media_id: str
    ) -> list[Appearance]: ...
    async def count_needs_review(self, school_id: str) -> int: ...
    async def event_match_counts(
        self, school_id: str
    ) -> dict[str, EventMatchCounts]: ...
    async def student_appearance_counts(
        self, school_id: str
    ) -> dict[str, StudentAppearanceCounts]: ...


class MatchCorrectionRepository(Protocol):
    """Backend-owned corrections over the ML ``matches`` (BP5, decisions/0042).

    Keyed on the stable ``(media_id, student_id)`` pair (upsert). The gallery reads overlay
    these onto the ML appearances (drop ``rejected``, union ``added``); the write use-cases
    live in the ``ReviewService``. Tenant-scoped by ``school_id``."""

    async def upsert(
        self,
        *,
        school_id: str,
        media_id: str,
        student_id: str,
        event_id: str,
        verdict: MatchVerdict,
        corrected_by: str | None,
        reason: str | None,
        resolves_review: bool,
    ) -> None: ...
    async def get(
        self, school_id: str, media_id: str, student_id: str
    ) -> MatchCorrection | None: ...
    async def delete(
        self, school_id: str, media_id: str, student_id: str
    ) -> None: ...
    async def list_for_media(
        self, school_id: str, media_id: str
    ) -> list[MatchCorrection]: ...
    async def list_for_event(
        self, school_id: str, event_id: str
    ) -> list[MatchCorrection]: ...
    async def list_for_student(
        self, school_id: str, student_id: str
    ) -> list[MatchCorrection]: ...
    async def count_resolved(self, school_id: str) -> int: ...
    async def monthly_verdict_counts(
        self, school_id: str
    ) -> dict[str, dict[MatchVerdict, int]]:
        """Corrections per calendar month × verdict (BP23 "Quality"), keyed ``'YYYY-MM'`` →
        verdict → count, on ``created_at``. Feeds the confirm-rate / reject-rate trend
        (``added`` excluded from the precision denominator). One grouped scan, tenant-scoped."""
        ...


class DownloadAuditRepository(Protocol):
    """Append-only audit of entitled media downloads (BP8b, decisions/0050).

    ``record`` is called best-effort on every successful signed-download mint (a failure
    must never block the download). The reads back the two school-admin surfaces: a
    per-media history and a paginated, filterable school-wide log. Tenant-scoped by
    ``school_id`` like every other repo; rows are immutable (no update/delete)."""

    async def record(
        self,
        *,
        school_id: str,
        media_id: str,
        event_id: str,
        actor_user_id: str,
        actor_role: str,
        subject_student_id: str | None,
    ) -> None: ...
    async def list_for_media(
        self, school_id: str, media_id: str, *, limit: int
    ) -> list[DownloadAuditEntry]: ...
    async def count_for_media(self, school_id: str, media_id: str) -> int: ...
    async def list_recent(
        self,
        school_id: str,
        *,
        limit: int,
        offset: int,
        event_id: str | None = None,
        student_id: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        actor_role: str | None = None,
    ) -> list[DownloadAuditEntry]:
        """One page of the school-wide access log, newest-first. BP28a adds a date-range
        (``created_from``/``created_to``, inclusive) + an ``actor_role`` filter (matched against
        the DENORMALIZED role column, so a deleted actor's rows still match)."""
        ...
    async def count_recent(
        self,
        school_id: str,
        *,
        event_id: str | None = None,
        student_id: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        actor_role: str | None = None,
    ) -> int: ...
    async def count_distinct_saver_students(self, school_id: str) -> int:
        """Distinct students who saved >=1 of their OWN photos (BP23 "Saved a photo") —
        distinct ``subject_student_id`` (non-null only on a self-download, so staff downloads
        are excluded). One DISTINCT scan, tenant-scoped."""
        ...
    async def download_counts_by_student_for_event(
        self, school_id: str, event_id: str
    ) -> dict[str, int]:
        """Per-student self-download count for one event (BP23 roster "Downloaded"). One
        grouped scan, tenant-scoped; only students with >=1 self-download appear."""
        ...


class AdminActionAuditRepository(Protocol):
    """Append-only audit of governance-lifecycle actions (BP28b, R4-A25).

    ``record`` is called best-effort by the single-writer services after a governance mutation
    succeeds (a failed audit must never block/roll back the mutation). ``list_recent`` /
    ``count_recent`` back the school-admin "Admin actions" tab — newest-first, tenant-scoped by
    ``school_id``, filterable by action / target / actor / date-range. The ``action`` and
    ``target_type`` filters compare the DENORMALIZED columns (no join), so a deleted actor's
    rows still match. Rows are immutable (no update/delete)."""

    async def record(
        self,
        *,
        school_id: str,
        actor_user_id: str | None,
        actor_role: str,
        action: str,
        target_type: str,
        target_id: str | None,
        target_label: str | None,
    ) -> None: ...
    async def list_recent(
        self,
        school_id: str,
        *,
        limit: int,
        offset: int,
        action: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        actor_user_id: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> list[AdminActionAuditEntry]:
        """One page of the admin-action log, newest-first (``created_at DESC, id DESC``).
        Optional filters — ``action``/``target_type`` (denormalized column compares),
        ``target_id``/``actor_user_id`` (id equality, malformed → empty), and an inclusive
        ``created_from``/``created_to`` window."""
        ...
    async def count_recent(
        self,
        school_id: str,
        *,
        action: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        actor_user_id: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> int: ...


class NotificationReadRepository(Protocol):
    """Per-(student, event) 'seen' state for the in-app new-photos signal (BP4,
    decisions/0041). Tenant-scoped by ``school_id`` like every other repo."""

    async def mark_seen(
        self, *, school_id: str, student_id: str, event_id: str
    ) -> None: ...
    async def list_for_student(
        self, school_id: str, student_id: str
    ) -> dict[str, datetime]: ...
    async def list_for_event(
        self, school_id: str, event_id: str
    ) -> dict[str, datetime]: ...
    async def count_distinct_seen_students(self, school_id: str) -> int:
        """Distinct students who have opened >=1 distribution (BP14 engagement) — the
        engagement-rate numerator. One grouped/DISTINCT scan, tenant-scoped."""
        ...
    async def distinct_opened_event_ids(self, school_id: str) -> list[str]:
        """Distinct event ids with >=1 opener (BP23 event-reach). The service intersects these
        with the currently-announced events so reach never over-reports. Seam-free — never the
        ML roster. One DISTINCT scan, tenant-scoped."""
        ...
    async def monthly_first_open_counts(self, school_id: str) -> dict[str, int]:
        """First-opens per calendar month (BP23 engagement trend), keyed ``'YYYY-MM'`` on the
        immutable ``created_at``. A decline-capable line. One grouped scan, tenant-scoped."""
        ...
    async def first_seen_for_event(
        self, school_id: str, event_id: str
    ) -> dict[str, datetime]:
        """Per-student FIRST-open time for one event (BP23 roster "ever opened") — the
        immutable ``created_at``, distinct from ``list_for_event``'s reset-on-reannounce
        ``seen_at``. Tenant-scoped."""
        ...


class NotificationChannel(Protocol):
    """One outbound notification channel (BP4, decisions/0041). Best-effort: the
    ``CompositeNotifier`` isolates failures, so an implementation may raise and it won't
    block the other channels. Channels are added by config (``BE_NOTIFICATION_CHANNELS``),
    so email/WhatsApp are future drop-ins with no service change."""

    async def notify(self, event: NotificationEvent) -> None: ...


class WhatsAppSender(Protocol):
    """Send one WhatsApp image message to a specific recipient (W1).

    Deliberately DISTINCT from :class:`NotificationChannel` (BP4). That port is the in-app,
    PII-free, best-effort, fire-and-forget announce fan-out — it takes a ``NotificationEvent``
    and returns nothing. This one is the outbound *WhatsApp* transport: it carries the
    recipient's phone number + the photo + the approved template/sender, and it RETURNS a
    receipt (the provider message id) or RAISES — a delivery attempt whose success matters.

    Provider-agnostic: no ``apikey``/``app_id`` concepts leak into the port (those are the
    Gupshup adapter's constructor concern). ``UpstreamError`` (→502) signals a transport
    failure / non-2xx; ``ValidationError`` (→400) a rejected recipient/template. W1 builds
    the sender but wires it into no service (there is no send endpoint yet — that is W2)."""

    async def send_image(
        self,
        *,
        to: str,
        image_url: str,
        template_name: str,
        sender_number: str,
        caption: str | None = None,
    ) -> WhatsAppReceipt: ...

    async def send_text(
        self, *, to: str, body: str, sender_number: str
    ) -> WhatsAppReceipt:
        """Send a FREE-FORM text message (no template) — the interim send's intro line
        (W-live-test). Only deliverable inside an open 24-hour customer window; raises
        ``UpstreamError`` (→502) on transport failure / non-2xx, ``ValidationError`` (→400) on a
        rejected recipient/window."""
        ...

    async def send_image_link(
        self,
        *,
        to: str,
        image_url: str,
        caption: str | None,
        sender_number: str,
    ) -> WhatsAppReceipt:
        """Send a FREE-FORM image message (no template) — the interim send's photos (W-live-test).
        Like ``send_text``, only inside an open 24-hour window. Same error contract."""
        ...


class PlatformConfigRepository(Protocol):
    """The platform-wide config singleton (W-live-test, migration 0024). Exactly ONE row, keyed
    on the constant id ``"platform"``. Holds the DB-stored Meta access token (a SECRET, never
    returned in full / never logged — the container reads it with an env fallback) + the interim
    free-form-send settings. Platform-admin only (authorization is at the route)."""

    async def get(self) -> PlatformConfig | None: ...
    async def upsert(
        self,
        *,
        meta_access_token: str | None,
        sender_number: str | None,
        interim_test_number: str | None,
        interim_mode: bool | None,
    ) -> PlatformConfig:
        """Create/replace the singleton, updating ONLY the provided (non-None) fields — a caller
        can save just the token, OR just the sender/interim number, without clobbering the rest (a
        fetch-merge upsert). ``None`` for any field means "leave unchanged"."""
        ...


class WhatsAppConfigRepository(Protocol):
    """Backend-owned, per-school NON-SECRET WhatsApp config (W1). Keyed on ``school_id`` (PK);
    reads are by that key, so tenant isolation is inherent. The one provider secret lives in
    settings, never in a column here."""

    async def get(self, school_id: str) -> SchoolWhatsAppConfig | None: ...
    async def upsert(
        self,
        *,
        school_id: str,
        enabled: bool,
        sender_number: str | None,
        template_name: str | None,
        business_name: str | None,
    ) -> SchoolWhatsAppConfig: ...


class WhatsAppSendLogRepository(Protocol):
    """Append-only audit of WhatsApp send attempts (W2, migration 0023).

    ``record`` inserts one immutable row per media attempted (``sent``/``failed``/``skipped``)
    best-effort — a failed audit must never abort a send batch. ``count_sent_since`` counts the
    ``sent`` rows since a boundary (the UTC month start) — the monthly budget cap. The recipient
    phone number is NEVER passed here (PII-free); ``error`` is a short PII-free reason.
    Tenant-scoped by ``school_id`` like every other repo; rows are immutable (no update/delete)."""

    async def record(
        self,
        *,
        school_id: str,
        student_id: str | None,
        media_id: str | None,
        actor_user_id: str | None,
        actor_role: str,
        sender_number: str,
        status: str,
        provider_message_id: str | None,
        error: str | None,
    ) -> None: ...
    async def count_sent_since(self, school_id: str, *, since: datetime) -> int:
        """Count ``status='sent'`` rows created at/after ``since`` for a school — the monthly
        budget count (``since`` = the UTC month start). Tenant-scoped."""
        ...
    async def list_for_student(
        self, school_id: str, student_id: str, *, limit: int
    ) -> list[WhatsAppSendLogEntry]:
        """A student's recent send history, newest-first (bounded by ``limit``). Tenant-scoped."""
        ...


class RateLimiter(Protocol):
    """A fixed-window request rate limiter (BP8c, decisions/0051).

    One ``acquire`` = one hit against ``key``'s current window; the HTTP middleware calls it
    once per tier (global / auth / per-school). Implementations are **fail-open** — a store
    outage returns ``allowed=True`` so a limiter failure never takes the API down."""

    async def acquire(
        self, key: str, *, limit: int, window_s: int
    ) -> RateLimitResult: ...


class PasswordHasher(Protocol):
    """Hash + verify passwords (argon2 adapter). No plaintext is ever stored."""

    def hash(self, plaintext: str) -> str: ...
    def verify(self, plaintext: str, hashed: str) -> bool: ...
    def needs_rehash(self, hashed: str) -> bool: ...


class TokenService(Protocol):
    """Issue + verify the self-signed access/refresh JWTs (decisions/0024)."""

    def issue_pair(self, user: User) -> TokenPair: ...
    def decode(self, token: str, *, expected_type: TokenType) -> TokenClaims: ...


class PermissionResolver(Protocol):
    """The single RBAC seam: what may this user do (decisions/0024)."""

    def permissions_for(self, user: User) -> frozenset[Permission]: ...
