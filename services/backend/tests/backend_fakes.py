"""Shared in-memory test doubles for the backend ports (decisions/0025).

These implement the domain Protocols structurally (so they type-check where a real
adapter is expected) without a DB or crypto. Kept in one place so successive phases
don't re-hand-roll them.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from backend.domain.emails import normalize_email
from backend.domain.errors import ConflictError, NotFoundError
from backend.domain.models import Role, School, SchoolStatus, User, UserStatus
from backend.domain.ports import SchoolRepository, UserRepository
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
        jwt_secret: str = _TEST_JWT_SECRET,
    ) -> None:
        super().__init__(Settings(jwt_secret=SecretStr(jwt_secret)))
        self._seed_users = users
        self._seed_schools: SchoolRepository = schools or FakeSchoolRepo()

    def user_repo(self) -> UserRepository:
        return self._seed_users

    def school_repo(self) -> SchoolRepository:
        return self._seed_schools
