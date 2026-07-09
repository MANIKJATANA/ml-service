"""Public user schema (decisions/0025).

The one shape a user is exposed as over the API — used by `/v1/auth/me` and by the
onboarding staff/admin routes. Built explicitly from the domain `User` so the
password hash can never leak.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from backend.domain.models import Role, User, UserStatus

# argon2 has no input cap (0024) — bound provisioning passwords at the edge.
_MAX_PASSWORD_LEN = 1024


class CreateUserRequest(BaseModel):
    """Provision a staff/admin account with a caller-set temp password (0025)."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=_MAX_PASSWORD_LEN)


class UserResponse(BaseModel):
    id: str
    email: str
    role: Role
    school_id: str | None
    status: UserStatus
    must_change_password: bool

    @classmethod
    def from_user(cls, user: User) -> UserResponse:
        return cls(
            id=user.id,
            email=user.email,
            role=user.role,
            school_id=user.school_id,
            status=user.status,
            must_change_password=user.must_change_password,
        )
