"""Request/response schemas for the auth routes (decisions/0024).

Pydantic lives only in the edge layers; the service/domain code speaks plain
dataclasses. Response models are built explicitly from domain objects so a password
hash can never leak through an over-broad `from_attributes`.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from backend.domain.models import Role, User, UserStatus
from backend.domain.tokens import TokenPair

# argon2 (unlike bcrypt) has no input-length cap, so it hashes the full string —
# an unbounded password would let an unauthenticated caller force arbitrarily
# expensive hashing on every request. Cap every password field at the edge (0024).
_MAX_PASSWORD_LEN = 1024


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=_MAX_PASSWORD_LEN)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=_MAX_PASSWORD_LEN)
    new_password: str = Field(min_length=8, max_length=_MAX_PASSWORD_LEN)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    must_change_password: bool

    @classmethod
    def from_pair(
        cls, pair: TokenPair, *, must_change_password: bool
    ) -> TokenResponse:
        return cls(
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            token_type=pair.token_type,
            expires_in=pair.expires_in,
            must_change_password=must_change_password,
        )


class MeResponse(BaseModel):
    id: str
    email: str
    role: Role
    school_id: str | None
    status: UserStatus
    must_change_password: bool

    @classmethod
    def from_user(cls, user: User) -> MeResponse:
        return cls(
            id=user.id,
            email=user.email,
            role=user.role,
            school_id=user.school_id,
            status=user.status,
            must_change_password=user.must_change_password,
        )
