"""Backend ports — the Protocol interfaces the services depend on.

Concrete implementations live under ``adapters/`` and are selected by config via
``wiring/registry.py`` (decisions/0022). Keeping services import-pure against these
Protocols (no SQLAlchemy/httpx/redis/supabase) is enforced by
``tests/test_layering.py``. The surface grows per phase; Phase 5 adds the event and
media repositories, the job producer, and the ML results reader (decisions/0027).
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from backend.domain.models import (
    EnrollmentOutcome,
    EnrollmentStatus,
    Event,
    EventJob,
    EventProcessingStatus,
    EventStatus,
    Media,
    MediaProcessingStatus,
    MediaType,
    Role,
    School,
    SignedUpload,
    Student,
    User,
)
from backend.domain.permissions import Permission
from backend.domain.tokens import TokenClaims, TokenPair, TokenType


class SchoolRepository(Protocol):
    async def create(self, *, name: str, max_teachers: int) -> School: ...
    async def get(self, school_id: str) -> School | None: ...
    async def list_all(self) -> list[School]: ...


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
    async def count_by_school_and_role(self, school_id: str, role: Role) -> int: ...
    async def list_by_school_and_role(
        self, school_id: str, role: Role
    ) -> list[User]: ...
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
        reference_photo_path: str,
    ) -> Student: ...
    async def get(self, school_id: str, student_id: str) -> Student | None: ...
    async def list_by_school(self, school_id: str) -> list[Student]: ...
    async def set_enrollment(
        self, student_id: str, *, status: EnrollmentStatus
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
    async def update(
        self,
        school_id: str,
        event_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        event_date: date | None = None,
        status: EventStatus | None = None,
    ) -> Event | None: ...
    async def set_processing(
        self, event_id: str, *, status: EventProcessingStatus
    ) -> None: ...


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
    ) -> Media: ...
    async def get(self, school_id: str, media_id: str) -> Media | None: ...
    async def list_by_event(self, school_id: str, event_id: str) -> list[Media]: ...
    async def status_counts(
        self, school_id: str, event_id: str
    ) -> dict[MediaProcessingStatus, int]: ...


class EventJobProducer(Protocol):
    """Enqueues one ML inference job per **event** (decisions/0027). Raises
    ``UpstreamError`` when the queue backend is unreachable."""

    async def enqueue(self, job: EventJob) -> None: ...


class ObjectStore(Protocol):
    """Mints a direct-to-storage upload target for a caller-chosen object key.

    The backend never handles the photo bytes — the frontend uploads to the signed
    URL and later submits the object path (decisions/0026)."""

    async def create_signed_upload_url(self, object_path: str) -> SignedUpload: ...


class MlEnrollmentClient(Protocol):
    """The backend's only outbound call to the ML service (decisions/0009).

    Synchronous enroll/refresh + delete of a student's embeddings. Raises
    ``UpstreamError`` when the ML service is unreachable or errors."""

    async def enroll(
        self, *, school_id: str, student_id: str, photo_uris: list[str]
    ) -> EnrollmentOutcome: ...
    async def delete(self, *, school_id: str, student_id: str) -> None: ...


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
