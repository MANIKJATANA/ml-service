"""Onboarding use-cases — schools + staff provisioning + lifecycle (decisions/0025, BP7c).

Depends only on the `SchoolRepository`, `UserRepository`, and `PasswordHasher` ports
(no RBAC, no HTTP) — authorization is enforced at the route via `require_permissions`,
and tenant scoping by the caller passing the authenticated user's `school_id` in.
Provisioned accounts get `must_change_password=True` and a **server-generated** temp
password returned exactly once (BP7c) — never stored plaintext, never returned again.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.domain.errors import (
    LimitExceededError,
    NotFoundError,
    ValidationError,
)
from backend.domain.models import (
    DEFAULT_EVENT_CATEGORIES,
    Role,
    School,
    SchoolStatus,
    User,
    UserSort,
    UserStatus,
)
from backend.domain.ports import (
    EventCategoryRepository,
    PasswordHasher,
    SchoolRepository,
    UserRepository,
)
from backend.services.credentials import generate_temp_password
from backend.services.pagination import Page

_MAX_NAME_LEN = 200


@dataclass(frozen=True, slots=True)
class ProvisionedUser:
    """A newly provisioned / re-invited account + its one-time plaintext temp password
    (BP7c). The password is surfaced once to the admin, then only the hash is kept."""

    user: User
    temp_password: str


class OnboardingService:
    def __init__(
        self,
        schools: SchoolRepository,
        users: UserRepository,
        hasher: PasswordHasher,
        categories: EventCategoryRepository,
    ) -> None:
        self._schools = schools
        self._users = users
        self._hasher = hasher
        self._categories = categories

    # ---- schools (platform) --------------------------------------------

    async def create_school(self, *, name: str, max_teachers: int) -> School:
        clean = name.strip()
        if not clean or len(clean) > _MAX_NAME_LEN:
            raise ValidationError("school name must be 1-200 characters")
        if max_teachers < 1:
            raise ValidationError("max_teachers must be >= 1")
        school = await self._schools.create(name=clean, max_teachers=max_teachers)
        # BP11b: every new school starts with the default event categories (admins/staff
        # add more). Seeded best-effort in the same flow — existing schools got them in
        # migration 0014.
        await self._categories.seed_defaults(school.id, DEFAULT_EVENT_CATEGORIES)
        return school

    async def list_schools(self) -> list[School]:
        return await self._schools.list_all()

    async def get_school(self, school_id: str) -> School:
        school = await self._schools.get(school_id)
        if school is None:
            raise NotFoundError(f"school not found: {school_id}")
        return school

    # ---- staff provisioning --------------------------------------------

    async def create_school_admin(
        self, *, school_id: str, email: str
    ) -> ProvisionedUser:
        await self.get_school(school_id)  # 404 if the school does not exist
        return await self._provision(
            school_id=school_id, email=email, role=Role.SCHOOL_ADMIN
        )

    async def create_teacher(
        self, *, school_id: str, email: str
    ) -> ProvisionedUser:
        school = await self.get_school(school_id)
        if school.status is not SchoolStatus.ACTIVE:
            raise ValidationError("school is suspended")
        # Cap counts teachers only (0025). Count-then-create races are accepted for
        # v1 (single admin per school does sequential creates); documented.
        current = await self._users.count_by_school_and_role(school_id, Role.TEACHER)
        if current >= school.max_teachers:
            raise LimitExceededError(
                f"teacher limit reached ({school.max_teachers}) for this school"
            )
        return await self._provision(
            school_id=school_id, email=email, role=Role.TEACHER
        )

    async def list_staff(self, *, school_id: str) -> list[User]:
        return await self._users.list_by_school_and_role(school_id, Role.TEACHER)

    async def list_staff_page(
        self,
        *,
        school_id: str,
        limit: int,
        offset: int,
        q: str | None = None,
        sort: UserSort = UserSort.CREATED_AT,
        descending: bool = True,
    ) -> Page[User]:
        """One page of a school's teacher roster (BP9). Searched on email + sorted
        server-side (users have no name/count columns)."""
        users = await self._users.list_page_by_role(
            school_id,
            Role.TEACHER,
            limit=limit,
            offset=offset,
            q=q,
            sort=sort,
            descending=descending,
        )
        total = await self._users.count_page_by_role(school_id, Role.TEACHER, q=q)
        return Page(items=users, total=total, limit=limit, offset=offset)

    # ---- staff lifecycle (BP7c) ----------------------------------------

    async def set_staff_status(
        self, *, school_id: str, user_id: str, role: Role, status: UserStatus
    ) -> User:
        """Enable/disable a teacher or admin. Tenant + role scoped (BP7c)."""
        user = await self._require_managed_user(
            school_id=school_id, user_id=user_id, role=role
        )
        if user.status is status:  # idempotent no-op — return current state
            return user
        await self._users.set_status(user_id, status=status)
        refreshed = await self._users.get(user_id)
        # The row was just updated; a read-miss is anomalous — reflect the new status.
        return refreshed if refreshed is not None else user

    async def resend_invite(
        self, *, school_id: str, user_id: str, role: Role
    ) -> ProvisionedUser:
        """Re-issue a temp password for a teacher/admin who hasn't signed in yet — or
        lost it (BP7c). Regenerates the password, forces a change on next login, and
        returns it once. Tenant + role scoped."""
        user = await self._require_managed_user(
            school_id=school_id, user_id=user_id, role=role
        )
        temp_password = generate_temp_password()
        await self._users.set_password(
            user_id,
            password_hash=self._hasher.hash(temp_password),
            must_change_password=True,
        )
        refreshed = await self._users.get(user_id)
        return ProvisionedUser(refreshed if refreshed is not None else user, temp_password)

    async def _require_managed_user(
        self, *, school_id: str, user_id: str, role: Role
    ) -> User:
        """Fetch a user that the caller is allowed to manage: it must exist, belong to
        ``school_id``, and have the expected ``role`` — else 404 (never leak that a
        user of another school/role exists). Blocks cross-tenant + wrong-route action
        and, since the manager is always a different role than the managed, self-action."""
        user = await self._users.get(user_id)
        if user is None or user.school_id != school_id or user.role is not role:
            raise NotFoundError(f"user not found: {user_id}")
        return user

    async def _provision(
        self, *, school_id: str, email: str, role: Role
    ) -> ProvisionedUser:
        temp_password = generate_temp_password()
        user = await self._users.create(
            school_id=school_id,
            email=email,
            password_hash=self._hasher.hash(temp_password),
            role=role,
            must_change_password=True,
        )
        return ProvisionedUser(user, temp_password)
