"""The JWT token service adapter (decisions/0024)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from backend.adapters.security.jwt_tokens import JwtTokenService
from backend.domain.errors import AuthenticationError, ConfigurationError
from backend.domain.models import Role, User, UserStatus
from backend.domain.tokens import TokenType


def _user(*, role: Role = Role.TEACHER, school_id: str | None = "school-1") -> User:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return User(
        id="user-1",
        school_id=school_id,
        email="t@x.io",
        password_hash="h",
        role=role,
        status=UserStatus.ACTIVE,
        must_change_password=False,
        created_at=now,
        updated_at=now,
    )


# ≥32 bytes, per RFC 7518 §3.2 for HS256 (PyJWT warns below that).
_SECRET = "test-secret-0123456789abcdef0123456789abcdef"


def _svc(*, secret: str = _SECRET, access_ttl: int = 900) -> JwtTokenService:
    return JwtTokenService(
        secret=secret,
        algorithm="HS256",
        issuer="backend",
        access_ttl_s=access_ttl,
        refresh_ttl_s=3600,
    )


def test_issue_and_decode_roundtrip() -> None:
    svc = _svc()
    pair = svc.issue_pair(_user())
    assert pair.token_type == "bearer" and pair.expires_in == 900

    access = svc.decode(pair.access_token, expected_type=TokenType.ACCESS)
    assert access.subject == "user-1"
    assert access.role is Role.TEACHER
    assert access.school_id == "school-1"

    # Refresh carries only the subject — no identity claims.
    refresh = svc.decode(pair.refresh_token, expected_type=TokenType.REFRESH)
    assert refresh.subject == "user-1"
    assert refresh.role is None and refresh.school_id is None


def test_platform_admin_has_null_school_claim() -> None:
    svc = _svc()
    pair = svc.issue_pair(_user(role=Role.PLATFORM_ADMIN, school_id=None))
    access = svc.decode(pair.access_token, expected_type=TokenType.ACCESS)
    assert access.role is Role.PLATFORM_ADMIN and access.school_id is None


def test_token_type_mismatch_rejected() -> None:
    svc = _svc()
    pair = svc.issue_pair(_user())
    # A refresh token must not pass as an access token, and vice versa.
    with pytest.raises(AuthenticationError):
        svc.decode(pair.refresh_token, expected_type=TokenType.ACCESS)
    with pytest.raises(AuthenticationError):
        svc.decode(pair.access_token, expected_type=TokenType.REFRESH)


def test_foreign_secret_rejected() -> None:
    pair = _svc(secret="one-secret-0123456789abcdef0123456789ab").issue_pair(_user())
    with pytest.raises(AuthenticationError):
        _svc(secret="two-secret-0123456789abcdef0123456789ab").decode(
            pair.access_token, expected_type=TokenType.ACCESS
        )


def test_expired_token_rejected() -> None:
    svc = _svc(access_ttl=-1)  # exp in the past
    pair = svc.issue_pair(_user())
    with pytest.raises(AuthenticationError):
        svc.decode(pair.access_token, expected_type=TokenType.ACCESS)


def test_garbage_token_rejected() -> None:
    with pytest.raises(AuthenticationError):
        _svc().decode("not.a.jwt", expected_type=TokenType.ACCESS)


def test_empty_secret_fails_loud() -> None:
    with pytest.raises(ConfigurationError):
        JwtTokenService(
            secret="",
            algorithm="HS256",
            issuer="backend",
            access_ttl_s=1,
            refresh_ttl_s=1,
        )
