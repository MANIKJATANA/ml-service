"""Auth token value types — pure, frozen (no third-party imports).

The `TokenService` port (`domain/ports.py`) speaks these; the JWT adapter
(`adapters/security/jwt_tokens.py`) is the only place they touch PyJWT. `TokenType`
distinguishes the short-lived access token from the long-lived refresh token so the
decode side can reject a refresh token presented as an access token, and vice versa.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from backend.domain.models import Role


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


@dataclass(frozen=True, slots=True)
class TokenPair:
    """What `login`/`refresh` hand back to the client."""

    access_token: str
    refresh_token: str
    expires_in: int  # access-token lifetime, seconds
    token_type: str = "bearer"  # OAuth2 scheme label for the Authorization header


@dataclass(frozen=True, slots=True)
class TokenClaims:
    """The verified contents of a decoded token.

    `role`/`school_id` are populated for access tokens and `None` for refresh tokens
    (which carry only the subject — identity is reloaded from the DB on refresh).
    """

    subject: str  # the user id
    token_type: TokenType
    issued_at: datetime
    expires_at: datetime
    role: Role | None = None
    school_id: str | None = None
