"""Shared in-memory test doubles for the backend ports (decisions/0025).

These implement the domain Protocols structurally (so they type-check where a real
adapter is expected) without a DB or crypto. Kept in one place so successive phases
don't re-hand-roll them.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from backend.adapters.whatsapp.fake_sender import FakeWhatsAppSender
from backend.domain.emails import normalize_email
from backend.domain.errors import ConflictError, NotFoundError, UpstreamError
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
    PhotoResult,
    PlatformConfig,
    Role,
    School,
    SchoolSort,
    SchoolStatus,
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
    WhatsAppSendLogEntry,
)
from backend.domain.ports import (
    AdminActionAuditRepository,
    DownloadAuditRepository,
    EventCategoryRepository,
    EventJobProducer,
    EventRepository,
    MatchCorrectionRepository,
    MediaRepository,
    MlEnrollmentClient,
    MlResultsReader,
    NotificationChannel,
    NotificationReadRepository,
    ObjectStore,
    PlatformConfigRepository,
    SchoolRepository,
    StudentGroupRepository,
    StudentRepository,
    TeacherClassRepository,
    Thumbnailer,
    UserRepository,
    WhatsAppSender,
    WhatsAppSendLogRepository,
)
from backend.domain.tokens import TokenClaims, TokenPair, TokenType
from backend.settings import Settings
from backend.wiring.container import Container
from pydantic import SecretStr

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_TEST_JWT_SECRET = "test-signing-key-0123456789abcdef0123"


# ---- BP9 pagination helpers for the repo fakes (decisions/0055) ----------


def _q_match(q: str | None, *fields: str) -> bool:
    """Case-insensitive substring match over any field — mirrors the adapters' ``ILIKE
    '%q%'``. An empty/whitespace ``q`` matches everything (the adapter only filters ``if
    q``)."""
    needle = (q or "").strip().lower()
    return not needle or any(needle in f.lower() for f in fields)


def _page[R](
    rows: list[R],
    *,
    key: Callable[[R], object],
    descending: bool,
    offset: int,
    limit: int,
) -> list[R]:
    """Sort by ``key`` with the row ``id`` as a stable tiebreak, then slice one page —
    mirrors the adapters' ``ORDER BY <col>, id`` + ``OFFSET/LIMIT``."""
    ordered = sorted(rows, key=lambda r: (key(r), r.id), reverse=descending)  # type: ignore[attr-defined]
    return ordered[offset : offset + limit]


# Row-native sort keys per entity (the count-column sorts are resolved in ListingService,
# never reach a fake's list_page). ``event_date`` maps None → date.min so a mixed list never
# compares a date with None.
_STUDENT_SORT_KEYS: dict[StudentSort, Callable[[Student], object]] = {
    StudentSort.NAME: lambda s: s.name,
    StudentSort.CREATED_AT: lambda s: s.created_at,
}
_EVENT_SORT_KEYS: dict[EventSort, Callable[[Event], object]] = {
    EventSort.EVENT_DATE: lambda e: (e.event_date is None, e.event_date or date.min),
    EventSort.NAME: lambda e: e.name,
    EventSort.CREATED_AT: lambda e: e.created_at,
}
_USER_SORT_KEYS: dict[UserSort, Callable[[User], object]] = {
    UserSort.EMAIL: lambda u: u.email,
    UserSort.CREATED_AT: lambda u: u.created_at,
    # BP23: nulls (never signed in) sort last on ASC — mirror the adapter (Postgres NULLS LAST).
    UserSort.LAST_LOGIN_AT: lambda u: (u.last_login_at is None, u.last_login_at or _NOW),
}
_SCHOOL_SORT_KEYS: dict[SchoolSort, Callable[[School], object]] = {
    SchoolSort.NAME: lambda s: s.name,
    SchoolSort.CREATED_AT: lambda s: s.created_at,
}


def make_user(
    *,
    id: str = "user-1",
    school_id: str | None = "school-1",
    email: str = "t@x.io",
    password_hash: str = "hash:pw",
    role: Role = Role.TEACHER,
    status: UserStatus = UserStatus.ACTIVE,
    must_change_password: bool = False,
    token_version: int = 0,
    last_login_at: datetime | None = None,
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
        token_version=token_version,
        last_login_at=last_login_at,
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
    reference_photo_path: str | None = "reference-photos/school-1/photo.jpg",
    reference_photo_thumbnail_path: str | None = None,
    enrollment_status: EnrollmentStatus = EnrollmentStatus.PENDING,
    enrollment_failure_reason: EnrollmentFailureReason | None = None,
    student_group_id: str | None = None,
    student_group_name: str | None = None,
    status: UserStatus = UserStatus.ACTIVE,
    mobile_number: str | None = None,
    whatsapp_opt_in: bool = False,
) -> Student:
    return Student(
        id=id,
        school_id=school_id,
        user_id=user_id,
        name=name,
        email=email,
        reference_photo_path=reference_photo_path,
        reference_photo_thumbnail_path=reference_photo_thumbnail_path,
        enrollment_status=enrollment_status,
        enrollment_failure_reason=enrollment_failure_reason,
        student_group_id=student_group_id,
        student_group_name=student_group_name,
        status=status,
        mobile_number=mobile_number,
        whatsapp_opt_in=whatsapp_opt_in,
        created_at=_NOW,
        updated_at=_NOW,
    )


def make_student_group(
    *,
    id: str = "class-1",
    school_id: str = "school-1",
    name: str = "Grade 3B",
    grade: str | None = "3",
    section: str | None = "B",
) -> StudentGroup:
    return StudentGroup(
        id=id,
        school_id=school_id,
        name=name,
        grade=grade,
        section=section,
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
    term: str | None = None,
    category_id: str | None = None,
    category_name: str | None = None,
    student_group_id: str | None = None,
    student_group_name: str | None = None,
    created_at: datetime = _NOW,
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
        created_at=created_at,
        updated_at=_NOW,
        term=term,
        category_id=category_id,
        category_name=category_name,
        student_group_id=student_group_id,
        student_group_name=student_group_name,
    )


def make_event_category(
    *,
    id: str = "cat-1",
    school_id: str = "school-1",
    name: str = "Sports",
) -> EventCategory:
    return EventCategory(
        id=id,
        school_id=school_id,
        name=name,
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
    thumbnail_path: str | None = None,
    uploaded_by: str | None = None,
    created_at: datetime = _NOW,
) -> Media:
    return Media(
        id=id,
        school_id=school_id,
        event_id=event_id,
        storage_path=storage_path,
        media_type=media_type,
        processing_status=processing_status,
        completed_at=completed_at,
        thumbnail_path=thumbnail_path,
        uploaded_by=uploaded_by,
        created_at=created_at,
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


def make_download_audit_entry(
    *,
    id: str = "audit-1",
    school_id: str = "school-1",
    media_id: str = "media-1",
    event_id: str = "event-1",
    actor_user_id: str | None = "user-1",
    actor_role: str = "school_admin",
    subject_student_id: str | None = None,
    created_at: datetime = _NOW,
) -> DownloadAuditEntry:
    return DownloadAuditEntry(
        id=id,
        school_id=school_id,
        media_id=media_id,
        event_id=event_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        subject_student_id=subject_student_id,
        created_at=created_at,
    )


def make_admin_action_audit_entry(
    *,
    id: str = "aa-1",
    school_id: str = "school-1",
    actor_user_id: str | None = "user-1",
    actor_role: str = "school_admin",
    action: str = "student_created",
    target_type: str = "student",
    target_id: str | None = "student-1",
    target_label: str | None = "Bart Simpson",
    created_at: datetime = _NOW,
) -> AdminActionAuditEntry:
    return AdminActionAuditEntry(
        id=id,
        school_id=school_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=action,
        target_type=target_type,
        target_id=target_id,
        target_label=target_label,
        created_at=created_at,
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
        # BP14: ids that have "signed in" (mirrors last_login_at being set). The domain User
        # has no last_login_at field, so track it here.
        self._signed_in: set[str] = set()
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

    def status_of(self, user_id: str) -> UserStatus:
        """Sync helper: the login status for a user_id — mirrors the repo JOIN (BP18d).
        Lets the student read model reflect a disable the moment ``set_status`` writes it."""
        user = self._by_id.get(user_id)
        return user.status if user is not None else UserStatus.ACTIVE

    def signed_in_of(self, user_id: str) -> bool:
        """Sync helper: has this login ever signed in? — mirrors last_login_at IS NOT NULL
        (BP23 never-signed-in filter)."""
        return user_id in self._signed_in

    async def get_by_email(self, email: str) -> User | None:
        return self._by_email.get(normalize_email(email))

    async def set_password(
        self,
        user_id: str,
        *,
        password_hash: str,
        must_change_password: bool,
        revoke_sessions: bool = True,
    ) -> None:
        self.set_calls.append((user_id, password_hash, must_change_password))
        if user_id not in self._by_id:
            raise NotFoundError(user_id)
        # BP18d: a real change/reset bumps token_version (revokes old sessions); a rehash
        # (revoke_sessions=False) leaves it — the password didn't change.
        tv = self._by_id[user_id].token_version + (1 if revoke_sessions else 0)
        self.mutate(
            user_id,
            password_hash=password_hash,
            must_change_password=must_change_password,
            token_version=tv,
        )

    async def set_status(self, user_id: str, *, status: UserStatus) -> None:
        if user_id not in self._by_id:
            raise NotFoundError(user_id)
        self.mutate(user_id, status=status)

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

    async def count_active_by_school_and_role(self, school_id: str, role: Role) -> int:
        return sum(
            1
            for u in self._by_id.values()
            if u.school_id == school_id
            and u.role is role
            and u.status is UserStatus.ACTIVE
        )

    async def list_by_school_and_role(self, school_id: str, role: Role) -> list[User]:
        return [
            u
            for u in self._by_id.values()
            if u.school_id == school_id and u.role is role
        ]

    def _match_role(
        self, u: User, school_id: str, role: Role, q: str | None
    ) -> bool:
        return (
            u.school_id == school_id and u.role is role and _q_match(q, u.email)
        )

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
        rows = [
            u for u in self._by_id.values() if self._match_role(u, school_id, role, q)
        ]
        return _page(
            rows,
            key=_USER_SORT_KEYS.get(sort, _USER_SORT_KEYS[UserSort.CREATED_AT]),
            descending=descending,
            offset=offset,
            limit=limit,
        )

    async def count_page_by_role(
        self, school_id: str, role: Role, *, q: str | None = None
    ) -> int:
        return sum(
            1 for u in self._by_id.values() if self._match_role(u, school_id, role, q)
        )

    async def role_counts_by_school(self) -> dict[str, dict[Role, int]]:
        counts: dict[str, dict[Role, int]] = {}
        for u in self._by_id.values():
            if u.school_id is None:  # platform admins excluded
                continue
            per = counts.setdefault(u.school_id, {})
            per[u.role] = per.get(u.role, 0) + 1
        return counts

    async def touch_last_login(self, user_id: str) -> None:
        if user_id in self._by_id:
            self._signed_in.add(user_id)
            # BP23: also stamp the read-model field (the count aggregates still read
            # ``_signed_in`` so existing tests that poke it directly keep working).
            self.mutate(user_id, last_login_at=_NOW)

    async def count_signed_in_by_school_and_role(
        self, school_id: str, role: Role
    ) -> int:
        return sum(
            1
            for u in self._by_id.values()
            if u.id in self._signed_in
            and u.school_id == school_id
            and u.role is role
        )

    async def signed_in_role_counts_by_school(self) -> dict[str, dict[Role, int]]:
        counts: dict[str, dict[Role, int]] = {}
        for u in self._by_id.values():
            if u.school_id is None or u.id not in self._signed_in:
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

    async def update(
        self,
        school_id: str,
        *,
        name: str | None = None,
        max_teachers: int | None = None,
        status: SchoolStatus | None = None,
    ) -> School | None:
        school = self._by_id.get(school_id)
        if school is None:
            return None
        changes: dict[str, object] = {}
        if name is not None:
            changes["name"] = name
        if max_teachers is not None:
            changes["max_teachers"] = max_teachers
        if status is not None:
            changes["status"] = status
        updated = replace(school, **changes)  # type: ignore[arg-type]
        self._by_id[school_id] = updated
        return updated

    async def list_all(self) -> list[School]:
        return list(self._by_id.values())

    async def list_page(
        self,
        *,
        limit: int,
        offset: int,
        q: str | None = None,
        sort: SchoolSort = SchoolSort.NAME,
        descending: bool = False,
    ) -> list[School]:
        rows = [s for s in self._by_id.values() if _q_match(q, s.name)]
        return _page(
            rows,
            key=_SCHOOL_SORT_KEYS.get(sort, _SCHOOL_SORT_KEYS[SchoolSort.NAME]),
            descending=descending,
            offset=offset,
            limit=limit,
        )

    async def count_page(self, *, q: str | None = None) -> int:
        return sum(1 for s in self._by_id.values() if _q_match(q, s.name))

    async def list_ids(self, *, q: str | None = None) -> list[str]:
        return [s.id for s in self._by_id.values() if _q_match(q, s.name)]

    async def list_by_ids(self, school_ids: Sequence[str]) -> list[School]:
        wanted = set(school_ids)
        return [s for s in self._by_id.values() if s.id in wanted]


class FakeStudentRepo:
    def __init__(self, students: list[Student] | None = None) -> None:
        self._by_id: dict[str, Student] = {s.id: s for s in (students or [])}
        self._seq = 0
        # Set to raise from create() to exercise the compensating-delete path (0026).
        self.fail_create: bool = False
        # Resolves a student's login email by user_id — mirrors the repo's users JOIN
        # (0033). Wired to the FakeUserRepo in tests; defaults to a placeholder.
        self._email_of: Callable[[str], str] = lambda _uid: "student@example.com"
        # Resolves a class name by group_id — mirrors the repo's student_groups LEFT JOIN
        # (BP11a). Wired to the FakeStudentGroupRepo in tests; defaults to None (un-classed).
        self._group_name_of: Callable[[str], str | None] = lambda _gid: None
        # Resolves a login status by user_id — mirrors the repo's users JOIN (BP18d). Unlike
        # email/class, status is written to the USER row (set_status), so it must be resolved
        # on every read (not snapshotted at create) for a disable to surface. Defaults active.
        self._status_of: Callable[[str], UserStatus] = lambda _uid: UserStatus.ACTIVE
        # BP23: has the student's login ever signed in? (by user_id) / has the student opened
        # any distribution? (by student_id) — mirror the users.last_login_at IS NULL filter +
        # the notification_reads NOT EXISTS anti-join. Default: unknown → treated as "never"
        # (so an unwired fake with never_* filters matches everyone, like an empty DB).
        self._signed_in_of: Callable[[str], bool] = lambda _uid: False
        self._opened_of: Callable[[str], bool] = lambda _sid: False

    def link_users(self, resolver: Callable[[str], str]) -> None:
        self._email_of = resolver

    def link_user_status(self, resolver: Callable[[str], UserStatus]) -> None:
        self._status_of = resolver

    def link_login_activity(self, resolver: Callable[[str], bool]) -> None:
        self._signed_in_of = resolver  # by user_id → has ever signed in (BP23)

    def link_opened(self, resolver: Callable[[str], bool]) -> None:
        self._opened_of = resolver  # by student_id → has opened >=1 distribution (BP23)

    def link_groups(self, resolver: Callable[[str], str | None]) -> None:
        self._group_name_of = resolver

    def _hydrate(self, student: Student) -> Student:
        """Reflect the linked login's CURRENT status on the read model — mirrors the users
        JOIN. Email/class are snapshotted on write; status must be resolved on read (BP18d)."""
        return replace(student, status=self._status_of(student.user_id))

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
            reference_photo_thumbnail_path=reference_photo_thumbnail_path,
            enrollment_status=EnrollmentStatus.PENDING,
            mobile_number=mobile_number,
            whatsapp_opt_in=whatsapp_opt_in,
        )
        self._by_id[student.id] = student
        return self._hydrate(student)

    async def get(self, school_id: str, student_id: str) -> Student | None:
        student = self._by_id.get(student_id)
        # Tenant-scoped: a foreign school never sees the row (mirrors the query).
        if student is None or student.school_id != school_id:
            return None
        return self._hydrate(student)

    async def get_by_user_id(self, school_id: str, user_id: str) -> Student | None:
        for student in self._by_id.values():
            if student.user_id == user_id and student.school_id == school_id:
                return self._hydrate(student)
        return None

    async def list_by_school(self, school_id: str) -> list[Student]:
        return [
            self._hydrate(s) for s in self._by_id.values() if s.school_id == school_id
        ]

    def _match(
        self,
        s: Student,
        school_id: str,
        q: str | None,
        status: EnrollmentStatus | None,
        student_group_id: str | None = None,
        scope_group_ids: Sequence[str] | None = None,
        never_signed_in: bool = False,
        never_opened: bool = False,
    ) -> bool:
        # BP11c focus: an un-classed student is in no teacher's scope (unlike events).
        in_scope = scope_group_ids is None or (
            s.student_group_id is not None and s.student_group_id in scope_group_ids
        )
        # BP23 activity filters: exclude those who HAVE signed in / HAVE opened.
        if never_signed_in and self._signed_in_of(s.user_id):
            return False
        if never_opened and self._opened_of(s.id):
            return False
        return (
            s.school_id == school_id
            and (status is None or s.enrollment_status is status)
            and (student_group_id is None or s.student_group_id == student_group_id)
            and in_scope
            and _q_match(q, s.name, s.email)
        )

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
        rows = [
            s
            for s in self._by_id.values()
            if self._match(
                s, school_id, q, status, student_group_id, scope_group_ids,
                never_signed_in, never_opened,
            )
        ]
        page = _page(
            rows,
            key=_STUDENT_SORT_KEYS.get(sort, _STUDENT_SORT_KEYS[StudentSort.CREATED_AT]),
            descending=descending,
            offset=offset,
            limit=limit,
        )
        return [self._hydrate(s) for s in page]

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
        return sum(
            1
            for s in self._by_id.values()
            if self._match(
                s, school_id, q, status, student_group_id, scope_group_ids,
                never_signed_in, never_opened,
            )
        )

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
        return [
            s.id
            for s in self._by_id.values()
            if self._match(
                s, school_id, q, status, student_group_id, scope_group_ids,
                never_signed_in, never_opened,
            )
        ]

    async def list_by_ids(
        self, school_id: str, student_ids: Sequence[str]
    ) -> list[Student]:
        wanted = set(student_ids)
        return [
            self._hydrate(s)
            for s in self._by_id.values()
            if s.school_id == school_id and s.id in wanted
        ]

    async def resolve_by_emails(
        self, school_id: str, emails: Sequence[str]
    ) -> list[Student]:
        wanted = {e.lower() for e in emails}
        return [
            self._hydrate(s)
            for s in self._by_id.values()
            if s.school_id == school_id and s.email.lower() in wanted
        ]

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

    async def enrolled_counts_by_school(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for student in self._by_id.values():
            if student.enrollment_status is EnrollmentStatus.ENROLLED:
                counts[student.school_id] = counts.get(student.school_id, 0) + 1
        return counts

    async def set_enrollment(
        self,
        student_id: str,
        *,
        status: EnrollmentStatus,
        failure_reason: EnrollmentFailureReason | None = None,
    ) -> None:
        if student_id not in self._by_id:
            raise NotFoundError(student_id)
        self._by_id[student_id] = replace(
            self._by_id[student_id],
            enrollment_status=status,
            enrollment_failure_reason=failure_reason,
        )

    async def set_reference_photo(
        self,
        student_id: str,
        *,
        reference_photo_path: str,
        reference_photo_thumbnail_path: str | None = None,
    ) -> None:
        if student_id not in self._by_id:
            raise NotFoundError(student_id)
        self._by_id[student_id] = replace(
            self._by_id[student_id],
            reference_photo_path=reference_photo_path,
            reference_photo_thumbnail_path=reference_photo_thumbnail_path,
        )

    async def set_group(
        self, student_id: str, *, student_group_id: str | None
    ) -> None:
        if student_id not in self._by_id:
            raise NotFoundError(student_id)
        name = (
            self._group_name_of(student_group_id)
            if student_group_id is not None
            else None
        )
        self._by_id[student_id] = replace(
            self._by_id[student_id],
            student_group_id=student_group_id,
            student_group_name=name,
        )

    async def set_group_bulk(
        self,
        school_id: str,
        *,
        student_group_id: str,
        student_ids: Sequence[str],
    ) -> int:
        name = self._group_name_of(student_group_id)
        n = 0
        for sid in student_ids:
            s = self._by_id.get(sid)
            if s is not None and s.school_id == school_id:  # tenant-scoped
                self._by_id[sid] = replace(
                    s, student_group_id=student_group_id, student_group_name=name
                )
                n += 1
        return n

    async def set_mobile(
        self, student_id: str, *, mobile_number: str | None, whatsapp_opt_in: bool
    ) -> None:
        if student_id not in self._by_id:
            raise NotFoundError(student_id)
        self._by_id[student_id] = replace(
            self._by_id[student_id],
            mobile_number=mobile_number,
            whatsapp_opt_in=whatsapp_opt_in,
        )

    def group_counts(self, school_id: str) -> dict[str, int]:
        """Sync helper: per-class member count — mirrors the grouped students scan the
        FakeStudentGroupRepo delegates to (BP11a)."""
        counts: dict[str, int] = {}
        for s in self._by_id.values():
            if s.school_id == school_id and s.student_group_id is not None:
                counts[s.student_group_id] = counts.get(s.student_group_id, 0) + 1
        return counts

    def unassign_group(self, group_id: str) -> None:
        """Cascade hook for FakeStudentGroupRepo.delete (students.student_group_id
        ON DELETE SET NULL, BP11a): clear the pointer on every member."""
        for sid, s in list(self._by_id.items()):
            if s.student_group_id == group_id:
                self._by_id[sid] = replace(
                    s, student_group_id=None, student_group_name=None
                )

    def remove_by_user(self, user_id: str) -> None:
        """Cascade hook for FakeUserRepo.delete (students.user_id ON DELETE CASCADE)."""
        for sid, s in list(self._by_id.items()):
            if s.user_id == user_id:
                del self._by_id[sid]


class FakeStudentGroupRepo:
    """StudentGroupRepository double (BP11a). Tenant-scoped like the real adapter. Optionally
    linked to a FakeStudentRepo so ``student_counts`` reflects real membership and ``delete``
    un-assigns members (the SET NULL cascade)."""

    def __init__(self, groups: list[StudentGroup] | None = None) -> None:
        self._by_id: dict[str, StudentGroup] = {g.id: g for g in (groups or [])}
        self._seq = 0
        self._count_of: Callable[[str], dict[str, int]] = lambda _sid: {}
        self._on_delete: Callable[[str], None] | None = None

    def link_students(
        self,
        counter: Callable[[str], dict[str, int]],
        *,
        on_delete: Callable[[str], None] | None = None,
    ) -> None:
        self._count_of = counter
        self._on_delete = on_delete

    def name_of(self, group_id: str) -> str | None:
        """Sync helper: the class name for a group_id (or None) — mirrors the LEFT JOIN."""
        g = self._by_id.get(group_id)
        return g.name if g is not None else None

    async def create(
        self, *, school_id: str, name: str, grade: str | None, section: str | None
    ) -> StudentGroup:
        self._seq += 1
        group = make_student_group(
            id=f"cls-{self._seq}",
            school_id=school_id,
            name=name,
            grade=grade,
            section=section,
        )
        self._by_id[group.id] = group
        return group

    async def get(self, school_id: str, group_id: str) -> StudentGroup | None:
        g = self._by_id.get(group_id)
        if g is None or g.school_id != school_id:  # tenant-scoped
            return None
        return g

    async def list_by_school(self, school_id: str) -> list[StudentGroup]:
        return [g for g in self._by_id.values() if g.school_id == school_id]

    async def update(
        self,
        school_id: str,
        group_id: str,
        *,
        name: str,
        grade: str | None,
        section: str | None,
    ) -> StudentGroup | None:
        g = await self.get(school_id, group_id)
        if g is None:
            return None
        updated = replace(g, name=name, grade=grade, section=section)
        self._by_id[group_id] = updated
        return updated

    async def delete(self, school_id: str, group_id: str) -> bool:
        g = await self.get(school_id, group_id)
        if g is None:
            return False
        del self._by_id[group_id]
        if self._on_delete is not None:
            self._on_delete(group_id)  # SET NULL: un-assign the class's students
        return True

    async def student_counts(self, school_id: str) -> dict[str, int]:
        return self._count_of(school_id)


class FakeObjectStore:
    """ObjectStore double: returns deterministic signed upload/download URLs and records
    deletes. ``fail_deletes`` makes ``delete`` raise ``UpstreamError`` (to exercise the
    BP8e retry/best-effort path); ``fail_delete_keys`` narrows that to specific keys (W3a
    best-effort reaper coverage)."""

    def __init__(
        self,
        *,
        fail_deletes: bool = False,
        fail_downloads: bool = False,
        fail_delete_keys: set[str] | None = None,
    ) -> None:
        self.deleted: list[str] = []
        self.delete_attempts = 0
        self._fail_deletes = fail_deletes
        self._fail_downloads = fail_downloads
        self._fail_delete_keys = fail_delete_keys or set()
        # BP17: the last object path a download URL was minted for — tests assert that the
        # thumbnail variant selects the stored thumb path (and full-res otherwise).
        self.last_download_path: str | None = None
        # BP17: objects the backend wrote via upload_bytes (path -> bytes) — tests assert a
        # thumbnail was generated + stored under the tenant/event prefix.
        self.uploaded: dict[str, bytes] = {}
        # W3a: per-key last-modified timestamp for list_prefix. ``upload_bytes`` stamps
        # ``_clock``; a test can seed/backdate a key with ``put_object`` to make "old" vs
        # "new" objects deterministically.
        self._modified: dict[str, datetime] = {}
        self._clock: datetime = _NOW

    async def create_signed_upload_url(self, object_path: str) -> SignedUpload:
        return SignedUpload(
            upload_url=f"https://uploads.test/{object_path}",
            object_path=object_path,
            token="fake-token",
        )

    async def create_signed_download_url(
        self, object_path: str, *, expires_in_s: int
    ) -> str:
        self.last_download_path = object_path
        return f"https://downloads.test/{object_path}?ttl={expires_in_s}"

    async def delete(self, object_path: str) -> None:
        self.delete_attempts += 1
        if self._fail_deletes or object_path in self._fail_delete_keys:
            raise UpstreamError(f"fake delete failed for {object_path}")
        self.deleted.append(object_path)
        self.uploaded.pop(object_path, None)
        self._modified.pop(object_path, None)

    async def download_bytes(self, object_path: str) -> bytes:
        # BP17: the backend reads a just-uploaded original to thumbnail it. Return
        # deterministic bytes (the content is irrelevant — the FakeThumbnailer ignores it);
        # ``fail_downloads`` exercises the best-effort path (generation → None).
        if self._fail_downloads:
            raise UpstreamError(f"fake download failed for {object_path}")
        return f"bytes:{object_path}".encode()

    async def upload_bytes(
        self, object_path: str, data: bytes, *, content_type: str
    ) -> None:
        self.uploaded[object_path] = data
        self._modified[object_path] = self._clock

    async def list_prefix(self, prefix: str) -> list[StoredObject]:
        # W3a: every uploaded key under ``prefix`` (a leading-slash-normalised, "/"-boundary
        # match so ``pfx`` never matches ``pfx-other``), with its recorded timestamp.
        base = prefix.strip("/")
        out: list[StoredObject] = []
        for key, data in self.uploaded.items():  # noqa: B007 - data unused, key is the point
            if key == base or key.startswith(base + "/"):
                out.append(
                    StoredObject(
                        key=key,
                        last_modified=self._modified.get(key, self._clock),
                    )
                )
        return out

    # ---- W3a test helpers ---------------------------------------------------
    def put_object(self, key: str, *, modified: datetime) -> None:
        """Seed one object with an explicit ``last_modified`` (to make old vs recent objects
        for the reaper). Bypasses ``_clock`` so a test controls the age directly."""
        self.uploaded[key] = b""
        self._modified[key] = modified

    def set_clock(self, now: datetime) -> None:
        """Set the timestamp ``upload_bytes`` stamps on new keys."""
        self._clock = now


class FakeThumbnailer:
    """Thumbnailer double (BP17): returns fixed bytes, or ``None`` when ``produces`` is False
    (to exercise the best-effort 'no thumbnail generated' path)."""

    def __init__(self, *, produces: bool = True) -> None:
        self._produces = produces
        self.calls = 0
        # W1: the last per-call size/quality override seen — tests assert the WhatsApp
        # variant passes its own (max_edge, quality), distinct from the BP17 defaults.
        self.last_override: tuple[int | None, int | None] | None = None

    async def make_thumbnail(
        self, data: bytes, *, max_edge: int | None = None, quality: int | None = None
    ) -> bytes | None:
        self.calls += 1
        self.last_override = (max_edge, quality)
        return b"thumb-bytes" if self._produces else None


class FakeMlClient:
    """MlEnrollmentClient double: records calls; configurable outcome/failure."""

    def __init__(
        self,
        *,
        embeddings_stored: int = 1,
        photo_status: str = "enrolled",
        raise_on_enroll: Exception | None = None,
        raise_on_delete: Exception | None = None,
    ) -> None:
        self._embeddings = embeddings_stored
        # Per-photo status the ML reports (e.g. "no_face"/"error" for BP7b failures).
        self._photo_status = photo_status
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
                PhotoResult(index=i, status=self._photo_status)
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
        # Optionally linked to a FakeMediaRepo so count_active_with_pending_media can see
        # which events have pending photos (mirrors the real EXISTS-on-pending-media join).
        self._media_repo: FakeMediaRepo | None = None
        # Resolves a category name by id — mirrors the event_categories LEFT JOIN (BP11b).
        self._category_name_of: Callable[[str], str | None] = lambda _cid: None
        # Resolves a class name by id — mirrors the student_groups LEFT JOIN (BP11c).
        self._group_name_of: Callable[[str], str | None] = lambda _gid: None

    def link_media(self, media_repo: FakeMediaRepo) -> None:
        self._media_repo = media_repo

    def link_categories(self, resolver: Callable[[str], str | None]) -> None:
        self._category_name_of = resolver

    def link_groups(self, resolver: Callable[[str], str | None]) -> None:
        self._group_name_of = resolver

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
    ) -> Event:
        self._seq += 1
        event = make_event(
            id=f"evt-{self._seq}",
            school_id=school_id,
            name=name,
            description=description,
            event_date=event_date,
            created_by=created_by,
            category_id=category_id,
            category_name=(
                self._category_name_of(category_id)
                if category_id is not None
                else None
            ),
            term=term,
            student_group_id=student_group_id,
            student_group_name=(
                self._group_name_of(student_group_id)
                if student_group_id is not None
                else None
            ),
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

    def _match(
        self,
        e: Event,
        school_id: str,
        q: str | None,
        status: EventStatus | None,
        category_id: str | None = None,
        term: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        student_group_id: str | None = None,
        scope_group_ids: Sequence[str] | None = None,
    ) -> bool:
        # BP11c focus: an untagged (school-wide) event shows for every focused teacher.
        in_scope = scope_group_ids is None or (
            e.student_group_id is None or e.student_group_id in scope_group_ids
        )
        return (
            e.school_id == school_id
            and (status is None or e.status is status)
            and (category_id is None or e.category_id == category_id)
            and (term is None or e.term == term)
            and (
                date_from is None
                or (e.event_date is not None and e.event_date >= date_from)
            )
            and (
                date_to is None
                or (e.event_date is not None and e.event_date <= date_to)
            )
            and (student_group_id is None or e.student_group_id == student_group_id)
            and in_scope
            and _q_match(q, e.name)
        )

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
        rows = [
            e
            for e in self._by_id.values()
            if self._match(
                e, school_id, q, status, category_id, term, date_from, date_to,
                student_group_id, scope_group_ids,
            )
        ]
        return _page(
            rows,
            key=_EVENT_SORT_KEYS.get(sort, _EVENT_SORT_KEYS[EventSort.EVENT_DATE]),
            descending=descending,
            offset=offset,
            limit=limit,
        )

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
    ) -> int:
        return sum(
            1
            for e in self._by_id.values()
            if self._match(
                e, school_id, q, status, category_id, term, date_from, date_to,
                student_group_id, scope_group_ids,
            )
        )

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
    ) -> list[str]:
        return [
            e.id
            for e in self._by_id.values()
            if self._match(
                e, school_id, q, status, category_id, term, date_from, date_to,
                student_group_id, scope_group_ids,
            )
        ]

    async def list_terms(self, school_id: str) -> list[str]:
        return sorted(
            {
                e.term
                for e in self._by_id.values()
                if e.school_id == school_id and e.term is not None
            }
        )

    def untag_category(self, category_id: str) -> None:
        """Cascade hook for FakeEventCategoryRepo.delete (events.category_id SET NULL)."""
        for eid, e in list(self._by_id.items()):
            if e.category_id == category_id:
                self._by_id[eid] = replace(
                    e, category_id=None, category_name=None
                )

    def untag_group(self, group_id: str) -> None:
        """Cascade hook for FakeStudentGroupRepo.delete (events.student_group_id SET NULL)."""
        for eid, e in list(self._by_id.items()):
            if e.student_group_id == group_id:
                self._by_id[eid] = replace(
                    e, student_group_id=None, student_group_name=None
                )

    async def list_by_ids(
        self, school_id: str, event_ids: Sequence[str]
    ) -> list[Event]:
        wanted = set(event_ids)
        return [
            e
            for e in self._by_id.values()
            if e.school_id == school_id and e.id in wanted
        ]

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

    async def count_active_with_pending_media(self, school_id: str) -> int:
        # BP19c: active, not-in-flight events with >=1 pending photo (catches a second batch,
        # not just never-processed events). Mirrors the real EXISTS-on-pending-media predicate.
        in_flight = (
            EventProcessingStatus.QUEUED,
            EventProcessingStatus.PROCESSING,
        )
        n = 0
        for event in self._by_id.values():
            if (
                event.school_id != school_id
                or event.status is not EventStatus.ACTIVE  # archived can't be Processed
                or event.processing_status in in_flight  # already being worked
            ):
                continue
            if self._media_repo is not None:
                media = await self._media_repo.list_by_event(school_id, event.id)
                if any(
                    m.processing_status is MediaProcessingStatus.PENDING for m in media
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

    async def distributed_counts_by_school(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self._by_id.values():
            if e.notified_at is not None or (
                e.auto_notify and e.completed_at is not None
            ):
                counts[e.school_id] = counts.get(e.school_id, 0) + 1
        return counts

    async def recent_event_counts_by_school(
        self, since: datetime
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self._by_id.values():
            if e.created_at is not None and e.created_at >= since:
                counts[e.school_id] = counts.get(e.school_id, 0) + 1
        return counts

    async def first_distributed_at_by_school(self) -> dict[str, datetime]:
        # BP23: earliest announce time per school = min(coalesce(notified_at, completed_at))
        # under the announced predicate. Mirrors the real MIN grouped scan.
        out: dict[str, datetime] = {}
        for e in self._by_id.values():
            announced = e.notified_at is not None or (
                e.auto_notify and e.completed_at is not None
            )
            if not announced:
                continue
            announce_at = e.notified_at if e.notified_at is not None else e.completed_at
            if announce_at is None:
                continue
            cur = out.get(e.school_id)
            if cur is None or announce_at < cur:
                out[e.school_id] = announce_at
        return out

    async def last_event_created_at_by_school(self) -> dict[str, datetime]:
        # BP23: most recent event created_at per school (the "no event since" idle anchor).
        out: dict[str, datetime] = {}
        for e in self._by_id.values():
            if e.created_at is None:
                continue
            cur = out.get(e.school_id)
            if cur is None or e.created_at > cur:
                out[e.school_id] = e.created_at
        return out

    async def monthly_event_date_counts(self, school_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self._by_id.values():
            if e.school_id != school_id or e.event_date is None:
                continue
            key = e.event_date.strftime("%Y-%m")
            counts[key] = counts.get(key, 0) + 1
        return counts

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
        # BP24 tri-state: UNSET = unchanged; None/"" = clear; a value = set (name resolved).
        if not isinstance(category_id, UnsetType):
            changes["category_id"] = category_id or None
            changes["category_name"] = (
                self._category_name_of(category_id) if category_id else None
            )
        if not isinstance(term, UnsetType):
            changes["term"] = term or None
        if not isinstance(student_group_id, UnsetType):
            changes["student_group_id"] = student_group_id or None
            changes["student_group_name"] = (
                self._group_name_of(student_group_id) if student_group_id else None
            )
        updated = replace(event, **changes)  # type: ignore[arg-type]
        self._by_id[event_id] = updated
        return updated

    async def set_status_bulk(
        self, school_id: str, event_ids: Sequence[str], *, status: EventStatus
    ) -> int:
        n = 0
        for eid in event_ids:
            e = self._by_id.get(eid)
            if e is not None and e.school_id == school_id:  # tenant-scoped
                self._by_id[eid] = replace(e, status=status)
                n += 1
        return n

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


class FakeEventCategoryRepo:
    """EventCategoryRepository double (BP11b). Tenant-scoped like the real adapter. Optionally
    linked to a FakeEventRepo so the event read carries the category name and ``delete`` un-tags
    its events (the SET NULL cascade)."""

    def __init__(self, categories: list[EventCategory] | None = None) -> None:
        self._by_id: dict[str, EventCategory] = {c.id: c for c in (categories or [])}
        self._seq = 0
        self._on_delete: Callable[[str], None] | None = None

    def link_events(self, on_delete: Callable[[str], None]) -> None:
        self._on_delete = on_delete

    def name_of(self, category_id: str) -> str | None:
        """Sync helper: the category name for an id (or None) — mirrors the LEFT JOIN."""
        c = self._by_id.get(category_id)
        return c.name if c is not None else None

    async def create(self, *, school_id: str, name: str) -> EventCategory:
        self._seq += 1
        cat = make_event_category(
            id=f"ecat-{self._seq}", school_id=school_id, name=name
        )
        self._by_id[cat.id] = cat
        return cat

    async def get(self, school_id: str, category_id: str) -> EventCategory | None:
        c = self._by_id.get(category_id)
        if c is None or c.school_id != school_id:  # tenant-scoped
            return None
        return c

    async def get_by_name(self, school_id: str, name: str) -> EventCategory | None:
        target = name.strip().lower()
        for c in self._by_id.values():
            if c.school_id == school_id and c.name.lower() == target:
                return c
        return None

    async def list_by_school(self, school_id: str) -> list[EventCategory]:
        return [c for c in self._by_id.values() if c.school_id == school_id]

    async def delete(self, school_id: str, category_id: str) -> bool:
        c = await self.get(school_id, category_id)
        if c is None:
            return False
        del self._by_id[category_id]
        if self._on_delete is not None:
            self._on_delete(category_id)  # SET NULL: un-tag the category's events
        return True

    async def seed_defaults(self, school_id: str, names: Sequence[str]) -> None:
        have = {
            c.name.lower()
            for c in self._by_id.values()
            if c.school_id == school_id
        }
        for name in names:
            if name.strip().lower() not in have:
                self._seq += 1
                self._by_id[f"ecat-{self._seq}"] = make_event_category(
                    id=f"ecat-{self._seq}", school_id=school_id, name=name
                )


class FakeTeacherClassRepo:
    """TeacherClassRepository double (BP11c). Stores ``(school_id, teacher_id, group_id)``
    tuples; tenant-scoped like the real adapter. ``add`` is idempotent (a set)."""

    def __init__(self, links: list[tuple[str, str, str]] | None = None) -> None:
        self._links: set[tuple[str, str, str]] = set(links or [])

    async def add(
        self, *, school_id: str, teacher_user_id: str, student_group_id: str
    ) -> None:
        self._links.add((school_id, teacher_user_id, student_group_id))

    async def remove(
        self, *, school_id: str, teacher_user_id: str, student_group_id: str
    ) -> bool:
        key = (school_id, teacher_user_id, student_group_id)
        if key in self._links:
            self._links.discard(key)
            return True
        return False

    async def replace_for_teacher(
        self,
        *,
        school_id: str,
        teacher_user_id: str,
        student_group_ids: Sequence[str],
    ) -> None:
        self._links = {
            link
            for link in self._links
            if not (link[0] == school_id and link[1] == teacher_user_id)
        }
        for gid in student_group_ids:
            self._links.add((school_id, teacher_user_id, gid))

    async def list_group_ids_for_teacher(
        self, school_id: str, teacher_user_id: str
    ) -> list[str]:
        return [
            g
            for (s, t, g) in self._links
            if s == school_id and t == teacher_user_id
        ]

    async def list_teacher_ids_for_group(
        self, school_id: str, student_group_id: str
    ) -> list[str]:
        return [
            t
            for (s, t, g) in self._links
            if s == school_id and g == student_group_id
        ]


class RecordingStudentRepo(FakeStudentRepo):
    """FakeStudentRepo that records which read the gallery took (BP9 de-rostering
    regression, decisions/0055): the de-rostered reads must call ``list_by_ids``, never
    the whole-roster ``list_by_school``."""

    def __init__(self, students: list[Student] | None = None) -> None:
        super().__init__(students)
        self.calls: list[str] = []

    async def list_by_school(self, school_id: str) -> list[Student]:
        self.calls.append("list_by_school")
        return await super().list_by_school(school_id)

    async def list_by_ids(
        self, school_id: str, student_ids: Sequence[str]
    ) -> list[Student]:
        self.calls.append("list_by_ids")
        return await super().list_by_ids(school_id, student_ids)


class RecordingEventRepo(FakeEventRepo):
    """FakeEventRepo that records list_by_school vs list_by_ids (BP9 de-rostering)."""

    def __init__(self, events: list[Event] | None = None) -> None:
        super().__init__(events)
        self.calls: list[str] = []

    async def list_by_school(self, school_id: str) -> list[Event]:
        self.calls.append("list_by_school")
        return await super().list_by_school(school_id)

    async def list_by_ids(
        self, school_id: str, event_ids: Sequence[str]
    ) -> list[Event]:
        self.calls.append("list_by_ids")
        return await super().list_by_ids(school_id, event_ids)


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
        thumbnail_path: str | None = None,
        uploaded_by: str | None = None,
    ) -> Media:
        self._seq += 1
        media = make_media(
            id=f"med-{self._seq}",
            school_id=school_id,
            event_id=event_id,
            storage_path=storage_path,
            media_type=media_type,
            thumbnail_path=thumbnail_path,
            uploaded_by=uploaded_by,
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

    def _match_event(
        self,
        m: Media,
        school_id: str,
        event_id: str,
        status: MediaProcessingStatus | None,
    ) -> bool:
        return (
            m.school_id == school_id
            and m.event_id == event_id
            and (status is None or m.processing_status is status)
        )

    async def list_page_by_event(
        self,
        school_id: str,
        event_id: str,
        *,
        limit: int,
        offset: int,
        status: MediaProcessingStatus | None = None,
    ) -> list[Media]:
        rows = [
            m
            for m in self._by_id.values()
            if self._match_event(m, school_id, event_id, status)
        ]
        return _page(
            rows,
            key=lambda m: m.created_at,
            descending=False,
            offset=offset,
            limit=limit,
        )

    async def count_page_by_event(
        self,
        school_id: str,
        event_id: str,
        *,
        status: MediaProcessingStatus | None = None,
    ) -> int:
        return sum(
            1
            for m in self._by_id.values()
            if self._match_event(m, school_id, event_id, status)
        )

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

    async def pending_counts_by_event(self, school_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for m in self._by_id.values():
            if (
                m.school_id == school_id
                and m.processing_status is MediaProcessingStatus.PENDING
            ):
                counts[m.event_id] = counts.get(m.event_id, 0) + 1
        return counts

    async def monthly_upload_counts(self, school_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for m in self._by_id.values():
            if m.school_id != school_id or m.created_at is None:
                continue
            key = m.created_at.strftime("%Y-%m")
            counts[key] = counts.get(key, 0) + 1
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

    async def monthly_verdict_counts(
        self, school_id: str
    ) -> dict[str, dict[MatchVerdict, int]]:
        # BP23: the fake MatchCorrection VO carries no created_at, so bucket every correction
        # into one month (_NOW). Enough to test the confirm/reject/added counts + FE rate math;
        # the real month bucketing is covered by the gated Postgres round-trip.
        if not self._by_pair:
            return {}
        month = _NOW.strftime("%Y-%m")
        per: dict[MatchVerdict, int] = {}
        for c in self._by_pair.values():
            per[c.verdict] = per.get(c.verdict, 0) + 1
        return {month: per}


class FakeDownloadAuditRepo:
    """DownloadAuditRepository double: an in-memory append-only list (BP8b).

    Filters by ``school_id`` like the real adapter; ``created_at`` increments per record so
    the newest-first ordering is deterministic. ``raise_on_record`` exercises the best-effort
    swallow in ``GalleryService.download_url`` (an audit failure must not fail a download)."""

    def __init__(
        self,
        entries: list[DownloadAuditEntry] | None = None,
        *,
        raise_on_record: Exception | None = None,
    ) -> None:
        self._rows: list[DownloadAuditEntry] = list(entries or [])
        self._seq = len(self._rows)
        self._raise = raise_on_record

    async def record(
        self,
        *,
        school_id: str,
        media_id: str,
        event_id: str,
        actor_user_id: str,
        actor_role: str,
        subject_student_id: str | None,
    ) -> None:
        if self._raise is not None:
            raise self._raise
        self._seq += 1
        self._rows.append(
            DownloadAuditEntry(
                id=f"audit-{self._seq}",
                school_id=school_id,
                media_id=media_id,
                event_id=event_id,
                actor_user_id=actor_user_id,
                actor_role=actor_role,
                subject_student_id=subject_student_id,
                created_at=_NOW + timedelta(seconds=self._seq),
            )
        )

    def _scoped(self, school_id: str) -> list[DownloadAuditEntry]:
        rows = [r for r in self._rows if r.school_id == school_id]
        rows.sort(key=lambda r: r.created_at, reverse=True)  # newest-first
        return rows

    async def list_for_media(
        self, school_id: str, media_id: str, *, limit: int
    ) -> list[DownloadAuditEntry]:
        return [r for r in self._scoped(school_id) if r.media_id == media_id][:limit]

    async def count_for_media(self, school_id: str, media_id: str) -> int:
        return sum(
            1 for r in self._rows if r.school_id == school_id and r.media_id == media_id
        )

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
        rows = self._filtered(
            school_id, event_id, student_id, created_from, created_to, actor_role
        )
        return rows[offset : offset + limit]

    async def count_recent(
        self,
        school_id: str,
        *,
        event_id: str | None = None,
        student_id: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        actor_role: str | None = None,
    ) -> int:
        return len(
            self._filtered(
                school_id, event_id, student_id, created_from, created_to, actor_role
            )
        )

    def _filtered(
        self,
        school_id: str,
        event_id: str | None,
        student_id: str | None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        actor_role: str | None = None,
    ) -> list[DownloadAuditEntry]:
        rows = self._scoped(school_id)
        if event_id is not None:
            rows = [r for r in rows if r.event_id == event_id]
        if student_id is not None:
            rows = [r for r in rows if r.subject_student_id == student_id]
        # BP28a: inclusive date-range window + denormalized actor-role, mirroring the real SQL.
        if created_from is not None:
            rows = [r for r in rows if r.created_at >= created_from]
        if created_to is not None:
            rows = [r for r in rows if r.created_at <= created_to]
        if actor_role is not None:
            rows = [r for r in rows if r.actor_role == actor_role]
        return rows

    async def count_distinct_saver_students(self, school_id: str) -> int:
        # BP23: distinct students who self-downloaded (subject_student_id non-null == a save).
        return len(
            {
                r.subject_student_id
                for r in self._rows
                if r.school_id == school_id and r.subject_student_id is not None
            }
        )

    async def download_counts_by_student_for_event(
        self, school_id: str, event_id: str
    ) -> dict[str, int]:
        # BP23 roster "Downloaded": per-student self-download count for one event.
        counts: dict[str, int] = {}
        for r in self._rows:
            if (
                r.school_id == school_id
                and r.event_id == event_id
                and r.subject_student_id is not None
            ):
                counts[r.subject_student_id] = counts.get(r.subject_student_id, 0) + 1
        return counts

    @property
    def rows(self) -> list[DownloadAuditEntry]:
        """Test accessor: every recorded row, in insertion order."""
        return list(self._rows)


class FakeAdminActionAuditRepo:
    """AdminActionAuditRepository double: an in-memory append-only list (BP28b).

    Filters by ``school_id`` like the real adapter; ``created_at`` increments per record so the
    newest-first ordering is deterministic. ``raise_on_record`` exercises the best-effort swallow
    in the single-writer services (a failed audit must never fail the mutation)."""

    def __init__(
        self,
        entries: list[AdminActionAuditEntry] | None = None,
        *,
        raise_on_record: Exception | None = None,
    ) -> None:
        self._rows: list[AdminActionAuditEntry] = list(entries or [])
        self._seq = len(self._rows)
        self._raise = raise_on_record

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
    ) -> None:
        if self._raise is not None:
            raise self._raise
        self._seq += 1
        self._rows.append(
            AdminActionAuditEntry(
                id=f"aa-{self._seq}",
                school_id=school_id,
                actor_user_id=actor_user_id,
                actor_role=actor_role,
                action=action,
                target_type=target_type,
                target_id=target_id,
                target_label=target_label,
                created_at=_NOW + timedelta(seconds=self._seq),
            )
        )

    def _filtered(
        self,
        school_id: str,
        action: str | None,
        target_type: str | None,
        target_id: str | None,
        actor_user_id: str | None,
        created_from: datetime | None,
        created_to: datetime | None,
    ) -> list[AdminActionAuditEntry]:
        rows = [r for r in self._rows if r.school_id == school_id]
        rows.sort(key=lambda r: r.created_at, reverse=True)  # newest-first
        if action is not None:
            rows = [r for r in rows if r.action == action]
        if target_type is not None:
            rows = [r for r in rows if r.target_type == target_type]
        if target_id is not None:
            rows = [r for r in rows if r.target_id == target_id]
        if actor_user_id is not None:
            rows = [r for r in rows if r.actor_user_id == actor_user_id]
        if created_from is not None:
            rows = [r for r in rows if r.created_at >= created_from]
        if created_to is not None:
            rows = [r for r in rows if r.created_at <= created_to]
        return rows

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
        rows = self._filtered(
            school_id, action, target_type, target_id, actor_user_id,
            created_from, created_to,
        )
        return rows[offset : offset + limit]

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
    ) -> int:
        return len(
            self._filtered(
                school_id, action, target_type, target_id, actor_user_id,
                created_from, created_to,
            )
        )

    @property
    def rows(self) -> list[AdminActionAuditEntry]:
        """Test accessor: every recorded row, in insertion order."""
        return list(self._rows)


class FakePlatformConfigRepo:
    """PlatformConfigRepository double (W-live-test): the singleton row (or None before any save).
    ``upsert`` is a PARTIAL update — a ``None`` field is left unchanged (fetch-merge), matching the
    real adapter — so a caller can save just the token or just the number/mode. ``updated_at``
    ticks per save so a re-save is observably newer."""

    _SINGLETON_ID = "platform"

    def __init__(self, config: PlatformConfig | None = None) -> None:
        self._row: PlatformConfig | None = config
        self._tick = 0

    async def get(self) -> PlatformConfig | None:
        return self._row

    async def upsert(
        self,
        *,
        meta_access_token: str | None,
        sender_number: str | None,
        template_name: str | None,
        interim_test_number: str | None,
        interim_mode: bool | None,
    ) -> PlatformConfig:
        self._tick += 1
        current = self._row

        def merge(value: str | None, cur: str | None) -> str | None:
            # None → keep; "" → clear (NULL); value → set (mirrors _merge_str in the pg adapter).
            if value is None:
                return cur
            return value or None

        created_at = current.created_at if current is not None else _NOW
        merged_token = merge(
            meta_access_token, current.meta_access_token if current else None
        )
        merged_sender = merge(
            sender_number, current.sender_number if current else None
        )
        merged_template = merge(
            template_name, current.template_name if current else None
        )
        merged_number = merge(
            interim_test_number, current.interim_test_number if current else None
        )
        merged_mode = (
            interim_mode
            if interim_mode is not None
            else (current.interim_mode if current else False)
        )
        self._row = PlatformConfig(
            id=self._SINGLETON_ID,
            meta_access_token=merged_token,
            sender_number=merged_sender,
            template_name=merged_template,
            interim_test_number=merged_number,
            interim_mode=merged_mode,
            created_at=created_at,
            updated_at=_NOW + timedelta(seconds=self._tick),
        )
        return self._row


class FakeWhatsAppSendLogRepo:
    """WhatsAppSendLogRepository double (W2): an in-memory append-only list. Filters by
    ``school_id`` like the real adapter; ``created_at`` increments per record so a newest-first
    read is deterministic. ``count_sent_since`` counts ``sent`` rows since a boundary (the
    budget cap). The recipient phone number is never recorded (PII-free)."""

    def __init__(self, entries: list[WhatsAppSendLogEntry] | None = None) -> None:
        self._rows: list[WhatsAppSendLogEntry] = list(entries or [])
        self._seq = len(self._rows)

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
    ) -> None:
        self._seq += 1
        self._rows.append(
            WhatsAppSendLogEntry(
                id=f"wa-send-{self._seq}",
                school_id=school_id,
                student_id=student_id,
                media_id=media_id,
                actor_user_id=actor_user_id,
                actor_role=actor_role,
                sender_number=sender_number,
                status=status,
                provider_message_id=provider_message_id,
                error=error,
                # Real "now" (not the fixed _NOW) so a seeded budget row + service-recorded rows
                # land in the SAME UTC calendar month the service's count_sent_since window uses.
                created_at=datetime.now(UTC) + timedelta(seconds=self._seq),
            )
        )

    async def count_sent_since(self, school_id: str, *, since: datetime) -> int:
        return sum(
            1
            for r in self._rows
            if r.school_id == school_id
            and r.status == "sent"
            and r.created_at >= since
        )

    async def list_for_student(
        self, school_id: str, student_id: str, *, limit: int
    ) -> list[WhatsAppSendLogEntry]:
        rows = [
            r
            for r in self._rows
            if r.school_id == school_id and r.student_id == student_id
        ]
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return rows[:limit]

    @property
    def rows(self) -> list[WhatsAppSendLogEntry]:
        """Test accessor: every recorded row, in insertion order."""
        return list(self._rows)


class FakeNotificationReadRepo:
    """NotificationReadRepository double: (student_id, event_id) -> seen_at.

    Also tracks the immutable ``created_at`` (the TRUE first-open) via ``setdefault`` — so it
    survives a re-open/re-notify while ``seen_at`` moves forward (BP23 first-open vs seen)."""

    def __init__(self) -> None:
        self._seen: dict[tuple[str, str], datetime] = {}
        self._created: dict[tuple[str, str], datetime] = {}

    async def mark_seen(
        self, *, school_id: str, student_id: str, event_id: str
    ) -> None:
        key = (student_id, event_id)
        self._seen[key] = _NOW
        self._created.setdefault(key, _NOW)  # first-open never moves

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

    async def count_distinct_seen_students(self, school_id: str) -> int:
        # School-agnostic like list_for_* here (the fake keys on (student, event) only);
        # tests seed one school, so distinct students == the engagement numerator.
        return len({sid for (sid, _eid) in self._seen})

    async def distinct_opened_event_ids(self, school_id: str) -> list[str]:
        # BP23 reach: the distinct event ids with >=1 opener (the service intersects with the
        # announced set). School-agnostic like the other reads here (tests seed one school).
        return list({eid for (_sid, eid) in self._seen})

    async def monthly_first_open_counts(self, school_id: str) -> dict[str, int]:
        # BP23 first-open trend: bucket the immutable first-open times by 'YYYY-MM'.
        counts: dict[str, int] = {}
        for when in self._created.values():
            key = when.strftime("%Y-%m")
            counts[key] = counts.get(key, 0) + 1
        return counts

    async def first_seen_for_event(
        self, school_id: str, event_id: str
    ) -> dict[str, datetime]:
        # BP23 roster "ever opened": the immutable first-open, keyed by student.
        return {
            sid: created
            for (sid, eid), created in self._created.items()
            if eid == event_id
        }

    def has_opened(self, student_id: str) -> bool:
        """Sync helper: has this student opened >=1 distribution? — mirrors the
        notification_reads EXISTS anti-join (BP23 never-opened filter)."""
        return any(sid == student_id for (sid, _eid) in self._seen)

    def set_seen(self, student_id: str, event_id: str, when: datetime) -> None:
        """Test helper: seed a read at a specific time (re-notify resurface tests). The
        first-open (created_at) is set once (setdefault) so it never moves on a later reseed."""
        key = (student_id, event_id)
        self._seen[key] = when
        self._created.setdefault(key, when)


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
        student_groups: StudentGroupRepository | None = None,
        teacher_classes: TeacherClassRepository | None = None,
        object_store: ObjectStore | None = None,
        ml_client: MlEnrollmentClient | None = None,
        thumbnailer: Thumbnailer | None = None,
        events: EventRepository | None = None,
        event_categories: EventCategoryRepository | None = None,
        media: MediaRepository | None = None,
        event_job_producer: EventJobProducer | None = None,
        ml_results_reader: MlResultsReader | None = None,
        match_corrections: MatchCorrectionRepository | None = None,
        download_audit: DownloadAuditRepository | None = None,
        admin_action_audit: AdminActionAuditRepository | None = None,
        notification_reads: NotificationReadRepository | None = None,
        notifier: NotificationChannel | None = None,
        whatsapp_sender: WhatsAppSender | None = None,
        whatsapp_send_log: WhatsAppSendLogRepository | None = None,
        platform_config: PlatformConfigRepository | None = None,
        jwt_secret: str = _TEST_JWT_SECRET,
    ) -> None:
        super().__init__(Settings(jwt_secret=SecretStr(jwt_secret)))
        self._seed_users = users
        self._seed_schools: SchoolRepository = schools or FakeSchoolRepo()
        self._seed_students: StudentRepository = students or FakeStudentRepo()
        self._seed_student_groups: StudentGroupRepository = (
            student_groups or FakeStudentGroupRepo()
        )
        self._seed_teacher_classes: TeacherClassRepository = (
            teacher_classes or FakeTeacherClassRepo()
        )
        self._seed_object_store: ObjectStore = object_store or FakeObjectStore()
        self._seed_ml_client: MlEnrollmentClient = ml_client or FakeMlClient()
        self._seed_thumbnailer: Thumbnailer = thumbnailer or FakeThumbnailer()
        self._seed_events: EventRepository = events or FakeEventRepo()
        self._seed_event_categories: EventCategoryRepository = (
            event_categories or FakeEventCategoryRepo()
        )
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
        self._seed_download_audit: DownloadAuditRepository = (
            download_audit or FakeDownloadAuditRepo()
        )
        self._seed_admin_action_audit: AdminActionAuditRepository = (
            admin_action_audit or FakeAdminActionAuditRepo()
        )
        self._seed_notification_reads: NotificationReadRepository = (
            notification_reads or FakeNotificationReadRepo()
        )
        self._seed_notifier: NotificationChannel = notifier or FakeNotificationChannel()
        # W2: the send path. FakeWhatsAppSender is a real deterministic adapter (records .sent);
        # the send log is the in-memory fake. Route tests keep handles to assert on both.
        self._seed_whatsapp_sender: WhatsAppSender = (
            whatsapp_sender or FakeWhatsAppSender()
        )
        self._seed_whatsapp_send_log: WhatsAppSendLogRepository = (
            whatsapp_send_log or FakeWhatsAppSendLogRepo()
        )
        # W-live-test: the platform config singleton (DB-stored Meta token + interim-send
        # settings). Default = empty (never saved → get() None → the service synthesizes a
        # disabled default, so interim mode is off and the template path runs unchanged).
        self._seed_platform_config: PlatformConfigRepository = (
            platform_config or FakePlatformConfigRepo()
        )
        # Wire the FK-cascade simulation so delete-student removes the profile too.
        if isinstance(self._seed_users, FakeUserRepo) and isinstance(
            self._seed_students, FakeStudentRepo
        ):
            self._seed_users.link_cascade(self._seed_students.remove_by_user)
            self._seed_students.link_users(self._seed_users.email_of)
            # BP18d: the student read model reflects the linked login's status (disable).
            self._seed_students.link_user_status(self._seed_users.status_of)
            # BP23: the never-signed-in filter reads the login's sign-in state.
            self._seed_students.link_login_activity(self._seed_users.signed_in_of)
        # BP23: the never-opened filter reads whether the student has any notification read.
        if isinstance(self._seed_students, FakeStudentRepo) and isinstance(
            self._seed_notification_reads, FakeNotificationReadRepo
        ):
            self._seed_students.link_opened(self._seed_notification_reads.has_opened)
        # Wire the class↔student links (BP11a): the student read carries its class name, the
        # classes list shows member counts, and deleting a class un-assigns its students —
        # and (BP11c) un-tags its events (both students.student_group_id + events.student_group_id
        # are ON DELETE SET NULL).
        if isinstance(self._seed_students, FakeStudentRepo) and isinstance(
            self._seed_student_groups, FakeStudentGroupRepo
        ):
            students = self._seed_students
            groups = self._seed_student_groups
            events = self._seed_events
            students.link_groups(groups.name_of)
            if isinstance(events, FakeEventRepo):
                events.link_groups(groups.name_of)  # events carry the class name (BP11c)

                def _on_group_delete(gid: str) -> None:
                    students.unassign_group(gid)  # SET NULL: un-assign the class's students
                    events.untag_group(gid)  # SET NULL: un-tag the class's events (BP11c)

                groups.link_students(students.group_counts, on_delete=_on_group_delete)
            else:
                groups.link_students(
                    students.group_counts, on_delete=students.unassign_group
                )
        # Let the event repo see media presence (the not_started-with-media alert).
        if isinstance(self._seed_events, FakeEventRepo) and isinstance(
            self._seed_media, FakeMediaRepo
        ):
            self._seed_events.link_media(self._seed_media)
        # Wire the event↔category links (BP11b): the event read carries its category name,
        # and deleting a category un-tags its events (SET NULL).
        if isinstance(self._seed_events, FakeEventRepo) and isinstance(
            self._seed_event_categories, FakeEventCategoryRepo
        ):
            self._seed_events.link_categories(self._seed_event_categories.name_of)
            self._seed_event_categories.link_events(self._seed_events.untag_category)

    def user_repo(self) -> UserRepository:
        return self._seed_users

    def school_repo(self) -> SchoolRepository:
        return self._seed_schools

    def student_repo(self) -> StudentRepository:
        return self._seed_students

    def student_group_repo(self) -> StudentGroupRepository:
        return self._seed_student_groups

    def teacher_class_repo(self) -> TeacherClassRepository:
        return self._seed_teacher_classes

    def object_store(self) -> ObjectStore:
        return self._seed_object_store

    def thumbnailer(self) -> Thumbnailer:
        return self._seed_thumbnailer

    def ml_enrollment_client(self) -> MlEnrollmentClient:
        return self._seed_ml_client

    def event_repo(self) -> EventRepository:
        return self._seed_events

    def event_category_repo(self) -> EventCategoryRepository:
        return self._seed_event_categories

    def media_repo(self) -> MediaRepository:
        return self._seed_media

    def event_job_producer(self) -> EventJobProducer:
        return self._seed_event_job_producer

    def ml_results_reader(self) -> MlResultsReader:
        return self._seed_ml_results_reader

    def match_correction_repo(self) -> MatchCorrectionRepository:
        return self._seed_match_corrections

    def download_audit_repo(self) -> DownloadAuditRepository:
        return self._seed_download_audit

    def admin_action_audit_repo(self) -> AdminActionAuditRepository:
        return self._seed_admin_action_audit

    def notification_reads_repo(self) -> NotificationReadRepository:
        return self._seed_notification_reads

    def notifier(self) -> NotificationChannel:
        return self._seed_notifier

    def whatsapp_sender(self) -> WhatsAppSender:
        return self._seed_whatsapp_sender

    def whatsapp_send_log_repo(self) -> WhatsAppSendLogRepository:
        return self._seed_whatsapp_send_log

    def platform_config_repo(self) -> PlatformConfigRepository:
        return self._seed_platform_config
