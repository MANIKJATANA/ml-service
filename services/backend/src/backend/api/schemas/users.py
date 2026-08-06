"""Public user schema (decisions/0025).

The one shape a user is exposed as over the API — used by `/v1/auth/me` and by the
onboarding staff/admin routes. Built explicitly from the domain `User` so the
password hash can never leak.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr

from backend.domain.models import Role, User, UserStatus
from backend.services.onboarding_service import ProvisionedUser
from backend.services.pagination import Page


class CreateUserRequest(BaseModel):
    """Provision a staff/admin account (BP7c). The temp password is generated
    server-side and returned once — the caller supplies only the email."""

    email: EmailStr


class UpdateUserStatusRequest(BaseModel):
    """Enable or disable a staff/admin account (BP7c). A disabled account can't log in
    or refresh (the auth service rejects it); re-enabling restores access."""

    status: UserStatus


class UserResponse(BaseModel):
    id: str
    email: str
    role: Role
    school_id: str | None
    status: UserStatus
    must_change_password: bool
    created_at: datetime  # BP2: staff "added" date + admin roster; harmless on /me
    # BP18b: the student's display name on /me (the shell shows it); null for staff/platform,
    # whose accounts have no name (only an email). Additive — defaults null on every other read.
    name: str | None = None

    @classmethod
    def from_user(cls, user: User, *, name: str | None = None) -> UserResponse:
        return cls(
            id=user.id,
            email=user.email,
            role=user.role,
            school_id=user.school_id,
            status=user.status,
            must_change_password=user.must_change_password,
            created_at=user.created_at,
            name=name,
        )


class ProvisionedUserResponse(BaseModel):
    """A freshly provisioned (or re-invited) account + its ONE-TIME temp password (BP7c).

    The plaintext temp password is returned exactly once — on create and on
    resend-invite — so the admin can hand it to the person; it is never stored in the
    clear and never returned again. The `user` carries `must_change_password=true`."""

    user: UserResponse
    temp_password: str

    @classmethod
    def from_provisioned(cls, p: ProvisionedUser) -> ProvisionedUserResponse:
        return cls(user=UserResponse.from_user(p.user), temp_password=p.temp_password)


class UserListPageResponse(BaseModel):
    """One page of a users roster (BP9) — the staff (teacher) list + the school-admin
    roster — plus the unpaginated total for the given search."""

    items: list[UserResponse]
    total: int
    limit: int
    offset: int

    @classmethod
    def from_page(cls, page: Page[User]) -> UserListPageResponse:
        return cls(
            items=[UserResponse.from_user(u) for u in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )
