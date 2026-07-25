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
    Appearance,
    DownloadAuditEntry,
    EnrollmentFailureReason,
    EnrollmentOutcome,
    EnrollmentStatus,
    Event,
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
    RateLimitResult,
    Role,
    School,
    SchoolSort,
    SignedUpload,
    Student,
    StudentAppearanceCounts,
    StudentSort,
    User,
    UserSort,
    UserStatus,
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
        self, user_id: str, *, password_hash: str, must_change_password: bool
    ) -> None: ...
    async def set_status(self, user_id: str, *, status: UserStatus) -> None: ...
    async def count_by_school_and_role(self, school_id: str, role: Role) -> int: ...
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
    ) -> list[Student]:
        """One page of the students list (BP9), searched/filtered/sorted in SQL. Only
        row-native ``sort`` members reach here; count-column sorts take the id-scan path
        (``list_ids``)."""
        ...
    async def count_page(
        self,
        school_id: str,
        *,
        q: str | None = None,
        status: EnrollmentStatus | None = None,
    ) -> int:
        """Total students matching the same ``q``/``status`` filter (the page's ``total``)."""
        ...
    async def list_ids(
        self,
        school_id: str,
        *,
        q: str | None = None,
        status: EnrollmentStatus | None = None,
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
    ) -> list[Event]:
        """One page of the events list (BP9). Row-native ``sort`` only; count sorts →
        ``list_ids`` (see ``StudentRepository.list_page``)."""
        ...
    async def count_page(
        self,
        school_id: str,
        *,
        q: str | None = None,
        status: EventStatus | None = None,
    ) -> int: ...
    async def list_ids(
        self,
        school_id: str,
        *,
        q: str | None = None,
        status: EventStatus | None = None,
    ) -> list[str]: ...
    async def list_by_ids(
        self, school_id: str, event_ids: Sequence[str]
    ) -> list[Event]: ...
    async def status_counts(self, school_id: str) -> EventRollup: ...
    async def count_not_started_with_media(self, school_id: str) -> int: ...
    async def count_distributed(self, school_id: str) -> int: ...
    async def counts_by_school(self) -> dict[str, int]: ...
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
    ) -> Event | None: ...
    async def set_processing(
        self, event_id: str, *, status: EventProcessingStatus
    ) -> None: ...
    async def mark_notified(self, event_id: str) -> None: ...


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


class Thumbnailer(Protocol):
    """Downscales an image to a small preview (BP17, decisions/0056). The one place image
    bytes are decoded in the backend — kept behind this port so ``domain``/``services`` stay
    free of image libraries (the concrete Pillow adapter is the only importer)."""

    async def make_thumbnail(self, data: bytes) -> bytes | None:
        """Return a small JPEG of ``data``, or ``None`` if it can't be produced (a non-image,
        a decode/encode error) — best-effort, so a bad image never fails the upload."""
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
    ) -> list[DownloadAuditEntry]: ...
    async def count_recent(
        self,
        school_id: str,
        *,
        event_id: str | None = None,
        student_id: str | None = None,
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


class NotificationChannel(Protocol):
    """One outbound notification channel (BP4, decisions/0041). Best-effort: the
    ``CompositeNotifier`` isolates failures, so an implementation may raise and it won't
    block the other channels. Channels are added by config (``BE_NOTIFICATION_CHANNELS``),
    so email/WhatsApp are future drop-ins with no service change."""

    async def notify(self, event: NotificationEvent) -> None: ...


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
