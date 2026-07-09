"""Onboarding use-cases — schools + staff provisioning (decisions/0025).

Depends only on the `SchoolRepository`, `UserRepository`, and `PasswordHasher` ports
(no RBAC, no HTTP) — authorization is enforced at the route via `require_permissions`,
and tenant scoping by the caller passing the authenticated user's `school_id` in.
Provisioned accounts are created with `must_change_password=True` and a caller-set
temp password (no SMTP in v1); the password is never returned.
"""

from __future__ import annotations

from backend.domain.errors import (
    LimitExceededError,
    NotFoundError,
    ValidationError,
)
from backend.domain.models import Role, School, SchoolStatus, User
from backend.domain.ports import PasswordHasher, SchoolRepository, UserRepository

_MAX_NAME_LEN = 200


class OnboardingService:
    def __init__(
        self,
        schools: SchoolRepository,
        users: UserRepository,
        hasher: PasswordHasher,
    ) -> None:
        self._schools = schools
        self._users = users
        self._hasher = hasher

    # ---- schools (platform) --------------------------------------------

    async def create_school(self, *, name: str, max_teachers: int) -> School:
        clean = name.strip()
        if not clean or len(clean) > _MAX_NAME_LEN:
            raise ValidationError("school name must be 1-200 characters")
        if max_teachers < 1:
            raise ValidationError("max_teachers must be >= 1")
        return await self._schools.create(name=clean, max_teachers=max_teachers)

    async def list_schools(self) -> list[School]:
        return await self._schools.list_all()

    async def get_school(self, school_id: str) -> School:
        school = await self._schools.get(school_id)
        if school is None:
            raise NotFoundError(f"school not found: {school_id}")
        return school

    # ---- staff provisioning --------------------------------------------

    async def create_school_admin(
        self, *, school_id: str, email: str, password: str
    ) -> User:
        await self.get_school(school_id)  # 404 if the school does not exist
        return await self._provision(
            school_id=school_id, email=email, password=password, role=Role.SCHOOL_ADMIN
        )

    async def create_teacher(
        self, *, school_id: str, email: str, password: str
    ) -> User:
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
            school_id=school_id, email=email, password=password, role=Role.TEACHER
        )

    async def list_staff(self, *, school_id: str) -> list[User]:
        return await self._users.list_by_school_and_role(school_id, Role.TEACHER)

    async def _provision(
        self, *, school_id: str, email: str, password: str, role: Role
    ) -> User:
        return await self._users.create(
            school_id=school_id,
            email=email,
            password_hash=self._hasher.hash(password),
            role=role,
            must_change_password=True,
        )
