"""Shared in-memory test doubles for the backend ports (decisions/0025).

These implement the domain Protocols structurally (so they type-check where a real
adapter is expected) without a DB or crypto. Kept in one place so successive phases
don't re-hand-roll them.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime

from backend.domain.emails import normalize_email
from backend.domain.errors import ConflictError, NotFoundError
from backend.domain.models import (
    Appearance,
    EnrollmentOutcome,
    EnrollmentStatus,
    Event,
    EventJob,
    EventMatchCounts,
    EventProcessingStatus,
    EventRollup,
    EventStatus,
    MatchCorrection,
    MatchVerdict,
    Media,
    MediaProcessingStatus,
    MediaType,
    NotificationEvent,
    PhotoResult,
    Role,
    School,
    SchoolStatus,
    SignedUpload,
    Student,
    StudentAppearanceCounts,
    User,
    UserStatus,
)
from backend.domain.ports import (
    EventJobProducer,
    EventRepository,
    MatchCorrectionRepository,
    MediaRepository,
    MlEnrollmentClient,
    MlResultsReader,
    NotificationChannel,
    NotificationReadRepository,
    ObjectStore,
    SchoolRepository,
    StudentRepository,
    UserRepository,
)
from backend.domain.tokens import TokenClaims, TokenPair, TokenType
from backend.settings import Settings
from backend.wiring.container import Container
from pydantic import SecretStr

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_TEST_JWT_SECRET = "test-signing-key-0123456789abcdef0123"


def make_user(
    *,
    id: str = "user-1",
    school_id: str | None = "school-1",
    email: str = "t@x.io",
    password_hash: str = "hash:pw",
    role: Role = Role.TEACHER,
    status: UserStatus = UserStatus.ACTIVE,
    must_change_password: bool = False,
) -> User:
    return User(
        id=id,
        school_id=school_id,
        email=email,
        password_hash=password_hash,
        role=role,
        status=status,
        must_change_password=must_change_password,
        created_at=_NOW,
        updated_at=_NOW,
    )


def make_school(
    *,
    id: str = "school-1",
    name: str = "Springfield Elementary",
    max_teachers: int = 5,
    status: SchoolStatus = SchoolStatus.ACTIVE,
) -> School:
    return School(
        id=id,
        name=name,
        max_teachers=max_teachers,
        status=status,
        created_at=_NOW,
        updated_at=_NOW,
    )


def make_student(
    *,
    id: str = "student-1",
    school_id: str = "school-1",
    user_id: str = "user-1",
    name: str = "Bart Simpson",
    email: str = "student@example.com",
    reference_photo_path: str = "reference-photos/school-1/photo.jpg",
    enrollment_status: EnrollmentStatus = EnrollmentStatus.PENDING,
) -> Student:
    return Student(
        id=id,
        school_id=school_id,
        user_id=user_id,
        name=name,
        email=email,
        reference_photo_path=reference_photo_path,
        enrollment_status=enrollment_status,
        created_at=_NOW,
        updated_at=_NOW,
    )


def make_event(
    *,
    id: str = "event-1",
    school_id: str = "school-1",
    name: str = "Sports Day",
    description: str | None = None,
    event_date: date | None = None,
    created_by: str | None = "user-1",
    status: EventStatus = EventStatus.ACTIVE,
    processing_status: EventProcessingStatus = EventProcessingStatus.NOT_STARTED,
    enqueued_at: datetime | None = None,
    completed_at: datetime | None = None,
    auto_notify: bool = True,
    notified_at: datetime | None = None,
) -> Event:
    return Event(
        id=id,
        school_id=school_id,
        name=name,
        description=description,
        event_date=event_date,
        created_by=created_by,
        status=status,
        processing_status=processing_status,
        enqueued_at=enqueued_at,
        completed_at=completed_at,
        auto_notify=auto_notify,
        notified_at=notified_at,
        created_at=_NOW,
        updated_at=_NOW,
    )


def make_media(
    *,
    id: str = "media-1",
    school_id: str = "school-1",
    event_id: str = "event-1",
    storage_path: str = "events/school-1/event-1/photo.jpg",
    media_type: MediaType = MediaType.IMAGE,
    processing_status: MediaProcessingStatus = MediaProcessingStatus.PENDING,
    completed_at: datetime | None = None,
) -> Media:
    return Media(
        id=id,
        school_id=school_id,
        event_id=event_id,
        storage_path=storage_path,
        media_type=media_type,
        processing_status=processing_status,
        completed_at=completed_at,
        created_at=_NOW,
        updated_at=_NOW,
    )


def make_appearance(
    *,
    student_id: str = "student-1",
    media_id: str = "media-1",
    event_id: str = "event-1",
    confidence: float = 0.9,
    needs_review: bool = False,
) -> Appearance:
    return Appearance(
        student_id=student_id,
        media_id=media_id,
        event_id=event_id,
        confidence=confidence,
        needs_review=needs_review,
    )


def make_match_correction(
    *,
    media_id: str = "media-1",
    student_id: str = "student-1",
    event_id: str = "event-1",
    verdict: MatchVerdict = MatchVerdict.CONFIRMED,
    resolves_review: bool = False,
) -> MatchCorrection:
    # NB: ``event_id`` defaults to "event-1". For ADDED corrections consumed by the
    # event-scoped reads (event_students / event_student_media, keyed on event_id),
    # pass event_id to match the media's event — else list_for_event won't surface it
    # and a test can pass for the wrong reason.
    return MatchCorrection(
        media_id=media_id,
        student_id=student_id,
        event_id=event_id,
        verdict=verdict,
        resolves_review=resolves_review,
    )


class FakeHasher:
    """Deterministic, DB/crypto-free PasswordHasher: hash(p) == 'hash:' + p."""

    def __init__(self, *, needs_rehash: bool = False) -> None:
        self._needs = needs_rehash

    def hash(self, plaintext: str) -> str:
        return f"hash:{plaintext}"

    def verify(self, plaintext: str, hashed: str) -> bool:
        return hashed == f"hash:{plaintext}"

    def needs_rehash(self, hashed: str) -> bool:
        return self._needs


class FakeTokens:
    """TokenService double: tokens are '<prefix>:<user-id>'; trusted verbatim."""

    def issue_pair(self, user: User) -> TokenPair:
        return TokenPair(
            access_token=f"a:{user.id}",
            refresh_token=f"r:{user.id}",
            expires_in=900,
        )

    def decode(self, token: str, *, expected_type: TokenType) -> TokenClaims:
        subject = token.split(":", 1)[1]
        return TokenClaims(
            subject=subject,
            token_type=expected_type,
            issued_at=_NOW,
            expires_at=_NOW,
        )


class FakeUserRepo:
    def __init__(self, users: list[User] | None = None) -> None:
        seed = users or []
        self._by_id: dict[str, User] = {u.id: u for u in seed}
        # Keyed on email with no school scope — mirrors the real global
        # uq_users_email (an email is unique across all schools).
        self._by_email: dict[str, User] = {u.email: u for u in seed}
        self.set_calls: list[tuple[str, str, bool]] = []
        self._seq = 0
        # Simulates the students.user_id ON DELETE CASCADE (0026): when linked to a
        # FakeStudentRepo, deleting a user also removes its student profile.
        self._cascade: Callable[[str], None] | None = None

    def link_cascade(self, cascade: Callable[[str], None]) -> None:
        self._cascade = cascade

    async def create(
        self,
        *,
        school_id: str | None,
        email: str,
        password_hash: str,
        role: Role,
        must_change_password: bool = False,
    ) -> User:
        norm = normalize_email(email)
        if norm in self._by_email:
            raise ConflictError(f"email already registered: {email}")
        self._seq += 1
        user = make_user(
            id=f"gen-{self._seq}",
            school_id=school_id,
            email=norm,
            password_hash=password_hash,
            role=role,
            must_change_password=must_change_password,
        )
        self._by_id[user.id] = user
        self._by_email[norm] = user
        return user

    async def get(self, user_id: str) -> User | None:
        return self._by_id.get(user_id)

    def email_of(self, user_id: str) -> str:
        """Sync helper: the login email for a user_id (or "") — mirrors the repo JOIN."""
        user = self._by_id.get(user_id)
        return user.email if user is not None else ""

    async def get_by_email(self, email: str) -> User | None:
        return self._by_email.get(normalize_email(email))

    async def set_password(
        self, user_id: str, *, password_hash: str, must_change_password: bool
    ) -> None:
        self.set_calls.append((user_id, password_hash, must_change_password))
        if user_id not in self._by_id:
            raise NotFoundError(user_id)
        self.mutate(
            user_id, password_hash=password_hash, must_change_password=must_change_password
        )

    async def delete(self, user_id: str) -> None:
        user = self._by_id.pop(user_id, None)
        if user is not None:
            self._by_email.pop(user.email, None)
        if self._cascade is not None:
            self._cascade(user_id)  # cascade the linked student profile

    async def count_by_school_and_role(self, school_id: str, role: Role) -> int:
        return sum(
            1
            for u in self._by_id.values()
            if u.school_id == school_id and u.role is role
        )

    async def list_by_school_and_role(self, school_id: str, role: Role) -> list[User]:
        return [
            u
            for u in self._by_id.values()
            if u.school_id == school_id and u.role is role
        ]

    async def role_counts_by_school(self) -> dict[str, dict[Role, int]]:
        counts: dict[str, dict[Role, int]] = {}
        for u in self._by_id.values():
            if u.school_id is None:  # platform admins excluded
                continue
            per = counts.setdefault(u.school_id, {})
            per[u.role] = per.get(u.role, 0) + 1
        return counts

    def mutate(self, user_id: str, **changes: object) -> None:
        """Test helper: replace a stored user's fields (simulate out-of-band change)."""
        user = self._by_id[user_id]
        updated = replace(user, **changes)  # type: ignore[arg-type]
        self._by_id[user_id] = updated
        self._by_email[user.email] = updated


class FakeSchoolRepo:
    def __init__(self, schools: list[School] | None = None) -> None:
        self._by_id: dict[str, School] = {s.id: s for s in (schools or [])}
        self._seq = 0

    async def create(self, *, name: str, max_teachers: int) -> School:
        self._seq += 1
        school = make_school(
            id=f"school-{self._seq}", name=name, max_teachers=max_teachers
        )
        self._by_id[school.id] = school
        return school

    async def get(self, school_id: str) -> School | None:
        return self._by_id.get(school_id)

    async def list_all(self) -> list[School]:
        return list(self._by_id.values())


class FakeStudentRepo:
    def __init__(self, students: list[Student] | None = None) -> None:
        self._by_id: dict[str, Student] = {s.id: s for s in (students or [])}
        self._seq = 0
        # Set to raise from create() to exercise the compensating-delete path (0026).
        self.fail_create: bool = False
        # Resolves a student's login email by user_id — mirrors the repo's users JOIN
        # (0033). Wired to the FakeUserRepo in tests; defaults to a placeholder.
        self._email_of: Callable[[str], str] = lambda _uid: "student@example.com"

    def link_users(self, resolver: Callable[[str], str]) -> None:
        self._email_of = resolver

    async def create(
        self, *, school_id: str, user_id: str, name: str, reference_photo_path: str
    ) -> Student:
        if self.fail_create:
            raise RuntimeError("simulated students-insert failure")
        self._seq += 1
        student = make_student(
            id=f"stu-{self._seq}",
            school_id=school_id,
            user_id=user_id,
            name=name,
            email=self._email_of(user_id),
            reference_photo_path=reference_photo_path,
            enrollment_status=EnrollmentStatus.PENDING,
        )
        self._by_id[student.id] = student
        return student

    async def get(self, school_id: str, student_id: str) -> Student | None:
        student = self._by_id.get(student_id)
        # Tenant-scoped: a foreign school never sees the row (mirrors the query).
        if student is None or student.school_id != school_id:
            return None
        return student

    async def get_by_user_id(self, school_id: str, user_id: str) -> Student | None:
        for student in self._by_id.values():
            if student.user_id == user_id and student.school_id == school_id:
                return student
        return None

    async def list_by_school(self, school_id: str) -> list[Student]:
        return [s for s in self._by_id.values() if s.school_id == school_id]

    async def enrollment_counts(
        self, school_id: str
    ) -> dict[EnrollmentStatus, int]:
        counts = {s: 0 for s in EnrollmentStatus}
        for student in self._by_id.values():
            if student.school_id == school_id:
                counts[student.enrollment_status] += 1
        return counts

    async def counts_by_school(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for student in self._by_id.values():
            counts[student.school_id] = counts.get(student.school_id, 0) + 1
        return counts

    async def set_enrollment(
        self, student_id: str, *, status: EnrollmentStatus
    ) -> None:
        if student_id not in self._by_id:
            raise NotFoundError(student_id)
        self._by_id[student_id] = replace(
            self._by_id[student_id], enrollment_status=status
        )

    def remove_by_user(self, user_id: str) -> None:
        """Cascade hook for FakeUserRepo.delete (students.user_id ON DELETE CASCADE)."""
        for sid, s in list(self._by_id.items()):
            if s.user_id == user_id:
                del self._by_id[sid]


class FakeObjectStore:
    """ObjectStore double: returns deterministic signed upload/download URLs."""

    async def create_signed_upload_url(self, object_path: str) -> SignedUpload:
        return SignedUpload(
            upload_url=f"https://uploads.test/{object_path}",
            object_path=object_path,
            token="fake-token",
        )

    async def create_signed_download_url(
        self, object_path: str, *, expires_in_s: int
    ) -> str:
        return f"https://downloads.test/{object_path}?ttl={expires_in_s}"


class FakeMlClient:
    """MlEnrollmentClient double: records calls; configurable outcome/failure."""

    def __init__(
        self,
        *,
        embeddings_stored: int = 1,
        raise_on_enroll: Exception | None = None,
        raise_on_delete: Exception | None = None,
    ) -> None:
        self._embeddings = embeddings_stored
        self._raise = raise_on_enroll
        self._raise_delete = raise_on_delete
        self.enroll_calls: list[tuple[str, str, list[str]]] = []
        self.delete_calls: list[tuple[str, str]] = []

    async def enroll(
        self, *, school_id: str, student_id: str, photo_uris: list[str]
    ) -> EnrollmentOutcome:
        self.enroll_calls.append((school_id, student_id, list(photo_uris)))
        if self._raise is not None:
            raise self._raise
        return EnrollmentOutcome(
            embeddings_stored=self._embeddings,
            photo_results=tuple(
                PhotoResult(index=i, status="enrolled")
                for i in range(len(photo_uris))
            ),
        )

    async def delete(self, *, school_id: str, student_id: str) -> None:
        if self._raise_delete is not None:
            raise self._raise_delete
        self.delete_calls.append((school_id, student_id))


class FakeEventRepo:
    def __init__(self, events: list[Event] | None = None) -> None:
        self._by_id: dict[str, Event] = {e.id: e for e in (events or [])}
        self._seq = 0
        # Optionally linked to a FakeMediaRepo so count_not_started_with_media can see
        # which events actually have photos (mirrors the real EXISTS join).
        self._media_repo: FakeMediaRepo | None = None

    def link_media(self, media_repo: FakeMediaRepo) -> None:
        self._media_repo = media_repo

    async def create(
        self,
        *,
        school_id: str,
        name: str,
        description: str | None,
        event_date: date | None,
        created_by: str | None,
    ) -> Event:
        self._seq += 1
        event = make_event(
            id=f"evt-{self._seq}",
            school_id=school_id,
            name=name,
            description=description,
            event_date=event_date,
            created_by=created_by,
        )
        self._by_id[event.id] = event
        return event

    async def get(self, school_id: str, event_id: str) -> Event | None:
        event = self._by_id.get(event_id)
        if event is None or event.school_id != school_id:
            return None  # tenant-scoped (mirrors the query)
        return event

    async def list_by_school(self, school_id: str) -> list[Event]:
        return [e for e in self._by_id.values() if e.school_id == school_id]

    async def counts_by_school(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self._by_id.values():
            counts[e.school_id] = counts.get(e.school_id, 0) + 1
        return counts

    async def status_counts(self, school_id: str) -> EventRollup:
        total = active = archived = processing = 0
        for event in self._by_id.values():
            if event.school_id != school_id:
                continue
            total += 1
            if event.status is EventStatus.ACTIVE:
                active += 1
            elif event.status is EventStatus.ARCHIVED:
                archived += 1
            if event.processing_status in (
                EventProcessingStatus.QUEUED,
                EventProcessingStatus.PROCESSING,
            ):
                processing += 1
        return EventRollup(
            total=total, active=active, archived=archived, processing=processing
        )

    async def count_not_started_with_media(self, school_id: str) -> int:
        n = 0
        for event in self._by_id.values():
            if (
                event.school_id != school_id
                or event.status is not EventStatus.ACTIVE  # archived can't be Processed
                or event.processing_status is not EventProcessingStatus.NOT_STARTED
            ):
                continue
            if self._media_repo is not None and await self._media_repo.list_by_event(
                school_id, event.id
            ):
                n += 1
        return n

    async def count_distributed(self, school_id: str) -> int:
        # Mirrors the real "announced" predicate (BP4/BP7a): a manual notified_at push
        # OR an auto_notify event that has completed.
        n = 0
        for event in self._by_id.values():
            if event.school_id != school_id:
                continue
            if event.notified_at is not None or (
                event.auto_notify and event.completed_at is not None
            ):
                n += 1
        return n

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
    ) -> Event | None:
        event = await self.get(school_id, event_id)
        if event is None:
            return None
        changes: dict[str, object] = {}
        if name is not None:
            changes["name"] = name
        if description is not None:
            changes["description"] = description
        if event_date is not None:
            changes["event_date"] = event_date
        if status is not None:
            changes["status"] = status
        if auto_notify is not None:
            changes["auto_notify"] = auto_notify
        updated = replace(event, **changes)  # type: ignore[arg-type]
        self._by_id[event_id] = updated
        return updated

    async def set_processing(
        self, event_id: str, *, status: EventProcessingStatus
    ) -> None:
        event = self._by_id.get(event_id)
        if event is None:
            return
        changes: dict[str, object] = {"processing_status": status}
        if status is EventProcessingStatus.QUEUED:
            changes["enqueued_at"] = _NOW
            # completed_at kept set-forward on redistribute (BP4, decisions/0041).
        elif status is EventProcessingStatus.COMPLETED:
            changes["completed_at"] = _NOW
        self._by_id[event_id] = replace(event, **changes)  # type: ignore[arg-type]

    async def mark_notified(self, event_id: str) -> None:
        event = self._by_id.get(event_id)
        if event is not None:
            self._by_id[event_id] = replace(event, notified_at=_NOW)


class FakeMediaRepo:
    def __init__(self, media: list[Media] | None = None) -> None:
        self._by_id: dict[str, Media] = {m.id: m for m in (media or [])}
        self._seq = 0

    async def create(
        self,
        *,
        school_id: str,
        event_id: str,
        storage_path: str,
        media_type: MediaType,
    ) -> Media:
        self._seq += 1
        media = make_media(
            id=f"med-{self._seq}",
            school_id=school_id,
            event_id=event_id,
            storage_path=storage_path,
            media_type=media_type,
        )
        self._by_id[media.id] = media
        return media

    async def get(self, school_id: str, media_id: str) -> Media | None:
        media = self._by_id.get(media_id)
        if media is None or media.school_id != school_id:
            return None  # tenant-scoped
        return media

    async def list_by_event(self, school_id: str, event_id: str) -> list[Media]:
        return [
            m
            for m in self._by_id.values()
            if m.school_id == school_id and m.event_id == event_id
        ]

    async def list_by_ids(
        self, school_id: str, media_ids: Sequence[str]
    ) -> list[Media]:
        wanted = set(media_ids)
        return [
            m
            for m in self._by_id.values()
            if m.school_id == school_id and m.id in wanted
        ]

    async def status_counts(
        self, school_id: str, event_id: str
    ) -> dict[MediaProcessingStatus, int]:
        counts = {s: 0 for s in MediaProcessingStatus}
        for m in await self.list_by_event(school_id, event_id):
            counts[m.processing_status] += 1
        return counts

    async def school_status_counts(
        self, school_id: str
    ) -> dict[MediaProcessingStatus, int]:
        counts = {s: 0 for s in MediaProcessingStatus}
        for m in self._by_id.values():
            if m.school_id == school_id:
                counts[m.processing_status] += 1
        return counts

    async def counts_by_event(self, school_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for m in self._by_id.values():
            if m.school_id == school_id:
                counts[m.event_id] = counts.get(m.event_id, 0) + 1
        return counts


class FakeEventJobProducer:
    """EventJobProducer double: records enqueued jobs; configurable failure."""

    def __init__(self, *, raise_on_enqueue: Exception | None = None) -> None:
        self._raise = raise_on_enqueue
        self.jobs: list[EventJob] = []

    async def enqueue(self, job: EventJob) -> None:
        if self._raise is not None:
            raise self._raise
        self.jobs.append(job)


class FakeMlResultsReader:
    """MlResultsReader double: filters a seeded list of matches ``Appearance``s.

    Tenant scoping isn't re-checked here (it's ignored): the GalleryService's
    require-guards use the tenant-scoped repos, so the reader is only ever reached
    intra-tenant — mirroring the real adapter, which still filters by school_id."""

    def __init__(self, appearances: list[Appearance] | None = None) -> None:
        self._appearances = list(appearances or [])

    async def list_event_appearances(
        self, school_id: str, event_id: str
    ) -> list[Appearance]:
        return [a for a in self._appearances if a.event_id == event_id]

    async def list_student_appearances(
        self, school_id: str, student_id: str
    ) -> list[Appearance]:
        return [a for a in self._appearances if a.student_id == student_id]

    async def list_media_appearances(
        self, school_id: str, media_id: str
    ) -> list[Appearance]:
        return [a for a in self._appearances if a.media_id == media_id]

    async def count_needs_review(self, school_id: str) -> int:
        return sum(1 for a in self._appearances if a.needs_review)

    async def event_match_counts(
        self, school_id: str
    ) -> dict[str, EventMatchCounts]:
        by_event: dict[str, set[str]] = {}
        review: dict[str, int] = {}
        for a in self._appearances:
            by_event.setdefault(a.event_id, set()).add(a.student_id)
            if a.needs_review:
                review[a.event_id] = review.get(a.event_id, 0) + 1
        return {
            event_id: EventMatchCounts(
                matched_students=len(students), needs_review=review.get(event_id, 0)
            )
            for event_id, students in by_event.items()
        }

    async def student_appearance_counts(
        self, school_id: str
    ) -> dict[str, StudentAppearanceCounts]:
        appearances: dict[str, int] = {}
        events: dict[str, set[str]] = {}
        for a in self._appearances:
            appearances[a.student_id] = appearances.get(a.student_id, 0) + 1
            events.setdefault(a.student_id, set()).add(a.event_id)
        return {
            student_id: StudentAppearanceCounts(
                appearance_count=n, event_count=len(events[student_id])
            )
            for student_id, n in appearances.items()
        }


class FakeMatchCorrectionRepo:
    """MatchCorrectionRepository double: keyed on (media_id, student_id). Ignores school_id
    scoping (tests use unique ids; the real adapter still filters by school_id)."""

    def __init__(self, corrections: list[MatchCorrection] | None = None) -> None:
        self._by_pair: dict[tuple[str, str], MatchCorrection] = {
            (c.media_id, c.student_id): c for c in (corrections or [])
        }

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
    ) -> None:
        self._by_pair[(media_id, student_id)] = MatchCorrection(
            media_id=media_id,
            student_id=student_id,
            event_id=event_id,
            verdict=verdict,
            resolves_review=resolves_review,
        )

    async def get(
        self, school_id: str, media_id: str, student_id: str
    ) -> MatchCorrection | None:
        return self._by_pair.get((media_id, student_id))

    async def delete(self, school_id: str, media_id: str, student_id: str) -> None:
        self._by_pair.pop((media_id, student_id), None)

    async def list_for_media(
        self, school_id: str, media_id: str
    ) -> list[MatchCorrection]:
        return [c for c in self._by_pair.values() if c.media_id == media_id]

    async def list_for_event(
        self, school_id: str, event_id: str
    ) -> list[MatchCorrection]:
        return [c for c in self._by_pair.values() if c.event_id == event_id]

    async def list_for_student(
        self, school_id: str, student_id: str
    ) -> list[MatchCorrection]:
        return [c for c in self._by_pair.values() if c.student_id == student_id]

    async def count_resolved(self, school_id: str) -> int:
        return sum(1 for c in self._by_pair.values() if c.resolves_review)


class FakeNotificationReadRepo:
    """NotificationReadRepository double: (student_id, event_id) -> seen_at."""

    def __init__(self) -> None:
        self._seen: dict[tuple[str, str], datetime] = {}

    async def mark_seen(
        self, *, school_id: str, student_id: str, event_id: str
    ) -> None:
        self._seen[(student_id, event_id)] = _NOW

    async def list_for_student(
        self, school_id: str, student_id: str
    ) -> dict[str, datetime]:
        return {
            eid: seen for (sid, eid), seen in self._seen.items() if sid == student_id
        }

    async def list_for_event(
        self, school_id: str, event_id: str
    ) -> dict[str, datetime]:
        return {
            sid: seen for (sid, eid), seen in self._seen.items() if eid == event_id
        }

    def set_seen(self, student_id: str, event_id: str, when: datetime) -> None:
        """Test helper: seed a read at a specific time (re-notify resurface tests)."""
        self._seen[(student_id, event_id)] = when


class FakeNotificationChannel:
    """NotificationChannel double: records sent events; optionally raises (to exercise
    the CompositeNotifier's best-effort isolation)."""

    def __init__(self, *, raise_on_notify: Exception | None = None) -> None:
        self._raise = raise_on_notify
        self.sent: list[NotificationEvent] = []

    async def notify(self, event: NotificationEvent) -> None:
        if self._raise is not None:
            raise self._raise
        self.sent.append(event)


class SeededContainer(Container):
    """Container with pre-seeded repos; JWT/argon2/RBAC/services stay real.

    Superset used by the HTTP route tests: pass in fake user/school repos (keep a
    handle to mutate them) and inject via ``app.dependency_overrides``.
    """

    def __init__(
        self,
        users: UserRepository,
        schools: SchoolRepository | None = None,
        *,
        students: StudentRepository | None = None,
        object_store: ObjectStore | None = None,
        ml_client: MlEnrollmentClient | None = None,
        events: EventRepository | None = None,
        media: MediaRepository | None = None,
        event_job_producer: EventJobProducer | None = None,
        ml_results_reader: MlResultsReader | None = None,
        match_corrections: MatchCorrectionRepository | None = None,
        notification_reads: NotificationReadRepository | None = None,
        notifier: NotificationChannel | None = None,
        jwt_secret: str = _TEST_JWT_SECRET,
    ) -> None:
        super().__init__(Settings(jwt_secret=SecretStr(jwt_secret)))
        self._seed_users = users
        self._seed_schools: SchoolRepository = schools or FakeSchoolRepo()
        self._seed_students: StudentRepository = students or FakeStudentRepo()
        self._seed_object_store: ObjectStore = object_store or FakeObjectStore()
        self._seed_ml_client: MlEnrollmentClient = ml_client or FakeMlClient()
        self._seed_events: EventRepository = events or FakeEventRepo()
        self._seed_media: MediaRepository = media or FakeMediaRepo()
        self._seed_event_job_producer: EventJobProducer = (
            event_job_producer or FakeEventJobProducer()
        )
        self._seed_ml_results_reader: MlResultsReader = (
            ml_results_reader or FakeMlResultsReader()
        )
        self._seed_match_corrections: MatchCorrectionRepository = (
            match_corrections or FakeMatchCorrectionRepo()
        )
        self._seed_notification_reads: NotificationReadRepository = (
            notification_reads or FakeNotificationReadRepo()
        )
        self._seed_notifier: NotificationChannel = notifier or FakeNotificationChannel()
        # Wire the FK-cascade simulation so delete-student removes the profile too.
        if isinstance(self._seed_users, FakeUserRepo) and isinstance(
            self._seed_students, FakeStudentRepo
        ):
            self._seed_users.link_cascade(self._seed_students.remove_by_user)
            self._seed_students.link_users(self._seed_users.email_of)
        # Let the event repo see media presence (the not_started-with-media alert).
        if isinstance(self._seed_events, FakeEventRepo) and isinstance(
            self._seed_media, FakeMediaRepo
        ):
            self._seed_events.link_media(self._seed_media)

    def user_repo(self) -> UserRepository:
        return self._seed_users

    def school_repo(self) -> SchoolRepository:
        return self._seed_schools

    def student_repo(self) -> StudentRepository:
        return self._seed_students

    def object_store(self) -> ObjectStore:
        return self._seed_object_store

    def ml_enrollment_client(self) -> MlEnrollmentClient:
        return self._seed_ml_client

    def event_repo(self) -> EventRepository:
        return self._seed_events

    def media_repo(self) -> MediaRepository:
        return self._seed_media

    def event_job_producer(self) -> EventJobProducer:
        return self._seed_event_job_producer

    def ml_results_reader(self) -> MlResultsReader:
        return self._seed_ml_results_reader

    def match_correction_repo(self) -> MatchCorrectionRepository:
        return self._seed_match_corrections

    def notification_reads_repo(self) -> NotificationReadRepository:
        return self._seed_notification_reads

    def notifier(self) -> NotificationChannel:
        return self._seed_notifier
