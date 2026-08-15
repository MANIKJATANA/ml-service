"""Self-signed JWT access/refresh tokens (PyJWT) — the only place JWT is imported.

Implements the `TokenService` port (decisions/0024). Access tokens carry the
identity claims (`role`, `school_id`) for convenience; refresh tokens carry only the
subject (identity is reloaded from the DB on refresh). `decode` verifies signature,
issuer, and expiry, and asserts the token's `type` matches what the caller expects,
so a refresh token can never be replayed as an access token.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt

from backend.domain.errors import AuthenticationError, ConfigurationError
from backend.domain.models import Role, User
from backend.domain.tokens import TokenClaims, TokenPair, TokenType


class JwtTokenService:
    def __init__(
        self,
        *,
        secret: str,
        algorithm: str,
        issuer: str,
        access_ttl_s: int,
        refresh_ttl_s: int,
    ) -> None:
        if not secret:
            # Fail loud at build time rather than minting unsigned-in-practice
            # tokens with an empty key (decisions/0024).
            raise ConfigurationError(
                "BE_JWT_SECRET is empty; set a signing key to issue tokens"
            )
        self._secret = secret
        self._algorithm = algorithm
        self._issuer = issuer
        self._access_ttl = access_ttl_s
        self._refresh_ttl = refresh_ttl_s

    def issue_pair(self, user: User) -> TokenPair:
        now = datetime.now(UTC)
        access = self._encode(
            now,
            ttl_s=self._access_ttl,
            claims={
                "sub": user.id,
                "type": TokenType.ACCESS.value,
                "role": user.role.value,
                "school_id": user.school_id,
                "tv": user.token_version,
            },
        )
        refresh = self._encode(
            now,
            ttl_s=self._refresh_ttl,
            claims={
                "sub": user.id,
                "type": TokenType.REFRESH.value,
                "tv": user.token_version,
            },
        )
        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_in=self._access_ttl,
        )

    def decode(self, token: str, *, expected_type: TokenType) -> TokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                issuer=self._issuer,
                options={"require": ["exp", "iat", "sub"]},
            )
        except jwt.InvalidTokenError as exc:  # expired, bad sig, wrong issuer, …
            raise AuthenticationError("invalid or expired token") from exc

        if payload.get("type") != expected_type.value:
            raise AuthenticationError(f"expected a {expected_type.value} token")

        subject = payload["sub"]
        if not isinstance(subject, str):
            raise AuthenticationError("invalid token subject")

        role_raw = payload.get("role")
        try:
            role = Role(role_raw) if role_raw is not None else None
        except ValueError as exc:
            raise AuthenticationError("invalid token role") from exc

        return TokenClaims(
            subject=subject,
            token_type=expected_type,
            issued_at=datetime.fromtimestamp(payload["iat"], tz=UTC),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
            role=role,
            school_id=payload.get("school_id"),
            # BP18d: default a token minted before this deploy (no `tv`) to 0, so it stays
            # valid for a user still at token_version 0 and is rejected once they bump it.
            token_version=int(payload.get("tv", 0)),
        )

    def _encode(
        self, now: datetime, *, ttl_s: int, claims: dict[str, object]
    ) -> str:
        payload: dict[str, object] = {
            **claims,
            "iss": self._issuer,
            "iat": now,
            "exp": now + timedelta(seconds=ttl_s),
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)
