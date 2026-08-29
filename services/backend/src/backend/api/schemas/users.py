"""Public user schema (decisions/0025).

The one shape a user is exposed as over the API — used by `/v1/auth/me` and by the
onboarding staff/admin routes. Built explicitly from the domain `User` so the
password hash can never leak.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from backend.domain.models import Role, User, UserStatus
from backend.services.onboarding_service import BulkStaffResult, ProvisionedUser
from backend.services.pagination import Page

# The most teacher emails one bulk invite can carry in a single request (BP27b). Comfortably
# above a real school's teacher count; over it is a 422 (schema-enforced, abuse guard).
_MAX_BULK_STAFF = 100


class CreateUserRequest(BaseModel):
    """Provision a staff/admin account (BP7c). The temp password is generated
    server-side and returned once — the caller supplies only the email."""

    email: EmailStr


class BulkStaffRequest(BaseModel):
    """Invite many teachers from a list of emails at once (BP27b). ``emails`` is a raw
    ``list[str]`` (NOT ``EmailStr``) on purpose — a single malformed email must be a per-row
    ``invalid`` in the service, not a 422 that rejects the whole batch. Only the count is capped
    here (abuse guard → 422)."""

    emails: list[str] = Field(min_length=1, max_length=_MAX_BULK_STAFF)


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
    # BP23: last successful sign-in (null = never signed in). The staff/admin roster shows it
    # as a "Last sign-in" column; harmless on /me. Additive.
    last_login_at: datetime | None = None

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
            last_login_at=user.last_login_at,
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


class BulkStaffResultResponse(BaseModel):
    """One email's outcome from a bulk teacher invite (BP27b). ``temp_password`` is the ONE-TIME
    plaintext — present ONLY on a ``created`` row (null otherwise). ``error`` holds a short message
    for ``invalid``/``error`` (never for ``duplicate``/``limit_reached``)."""

    email: str
    status: Literal["created", "duplicate", "invalid", "limit_reached", "error"]
    temp_password: str | None = None
    error: str | None = None

    @classmethod
    def from_result(cls, r: BulkStaffResult) -> BulkStaffResultResponse:
        return cls(
            email=r.email,
            status=r.status,
            temp_password=r.temp_password,
            error=r.error,
        )


class BulkStaffResponse(BaseModel):
    """The per-email outcomes of a bulk teacher invite (BP27b). The response carries the created
    teachers' ONE-TIME temp passwords (each on its ``created`` row) — shown once so the admin can
    hand them out; only their hashes are stored, and they are never returned again."""

    results: list[BulkStaffResultResponse]

    @classmethod
    def from_results(cls, results: list[BulkStaffResult]) -> BulkStaffResponse:
        return cls(results=[BulkStaffResultResponse.from_result(r) for r in results])


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
