"""AuthService use-cases with fakes (decisions/0024) — no crypto, no DB.

The service depends only on ports, so fakes fully exercise login / refresh /
change-password without argon2 or PyJWT.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from backend.domain.errors import AuthenticationError
from backend.domain.models import Role, User, UserStatus
from backend.domain.tokens import TokenClaims, TokenPair, TokenType
from backend.services.auth_service import AuthService

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _user(**over: object) -> User:
    base = dict(
        id="user-1",
        school_id="school-1",
        email="t@x.io",
        password_hash="hash:pw",
        role=Role.TEACHER,
        status=UserStatus.ACTIVE,
        must_change_password=False,
        created_at=_NOW,
        updated_at=_NOW,
    )
    base.update(over)
    return User(**base)  # type: ignore[arg-type]


class FakeUserRepo:
    def __init__(self, users: list[User]) -> None:
        self._by_email = {u.email: u for u in users}
        self._by_id = {u.id: u for u in users}
        self.set_calls: list[tuple[str, str, bool]] = []

    async def create(
        self,
        *,
        school_id: str | None,
        email: str,
        password_hash: str,
        role: Role,
        must_change_password: bool = False,
    ) -> User:  # pragma: no cover - unused by these tests
        raise NotImplementedError

    async def get(self, user_id: str) -> User | None:
        return self._by_id.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        return self._by_email.get(email)

    async def set_password(
        self, user_id: str, *, password_hash: str, must_change_password: bool
    ) -> None:
        self.set_calls.append((user_id, password_hash, must_change_password))
        user = self._by_id[user_id]
        updated = replace(
            user,
            password_hash=password_hash,
            must_change_password=must_change_password,
        )
        self._by_id[user_id] = updated
        self._by_email[user.email] = updated


class FakeHasher:
    def __init__(self, *, needs_rehash: bool = False) -> None:
        self._needs = needs_rehash

    def hash(self, plaintext: str) -> str:
        return f"hash:{plaintext}"

    def verify(self, plaintext: str, hashed: str) -> bool:
        return hashed == f"hash:{plaintext}"

    def needs_rehash(self, hashed: str) -> bool:
        return self._needs


class FakeTokens:
    def issue_pair(self, user: User) -> TokenPair:
        return TokenPair(
            access_token=f"a:{user.id}",
            refresh_token=f"r:{user.id}",
            expires_in=900,
        )

    def decode(self, token: str, *, expected_type: TokenType) -> TokenClaims:
        # tokens look like "<prefix>:<user-id>"; trust them in the fake.
        subject = token.split(":", 1)[1]
        return TokenClaims(
            subject=subject,
            token_type=expected_type,
            issued_at=_NOW,
            expires_at=_NOW,
        )


def _service(
    users: list[User], *, needs_rehash: bool = False
) -> tuple[AuthService, FakeUserRepo]:
    repo = FakeUserRepo(users)
    svc = AuthService(repo, FakeHasher(needs_rehash=needs_rehash), FakeTokens())
    return svc, repo


async def test_login_success_returns_tokens_and_flag() -> None:
    svc, _ = _service([_user(must_change_password=True)])
    result = await svc.login(email="t@x.io", password="pw")
    assert result.tokens.access_token == "a:user-1"
    assert result.user.must_change_password is True


async def test_login_wrong_password_is_generic_401() -> None:
    svc, _ = _service([_user()])
    with pytest.raises(AuthenticationError):
        await svc.login(email="t@x.io", password="nope")


async def test_login_unknown_email_is_generic_401() -> None:
    # Missing user still runs a verify against the equalizer hash — no crash, no leak.
    svc, _ = _service([_user()])
    with pytest.raises(AuthenticationError):
        await svc.login(email="ghost@x.io", password="pw")


async def test_login_disabled_user_rejected() -> None:
    svc, _ = _service([_user(status=UserStatus.DISABLED)])
    with pytest.raises(AuthenticationError):
        await svc.login(email="t@x.io", password="pw")


async def test_login_rehashes_when_params_stale() -> None:
    svc, repo = _service([_user(must_change_password=True)], needs_rehash=True)
    await svc.login(email="t@x.io", password="pw")
    # Re-hashed, preserving the must-change flag (not a password change).
    assert repo.set_calls == [("user-1", "hash:pw", True)]


async def test_refresh_success() -> None:
    svc, _ = _service([_user()])
    result = await svc.refresh(refresh_token="r:user-1")
    assert result.tokens.refresh_token == "r:user-1"


async def test_refresh_reflects_role_change() -> None:
    # The reason refresh reloads identity (0024): a role/tenant change takes effect
    # on the next refresh, not at token expiry. FakeTokens ignores claims, so this
    # asserts the service reloads the *current* user and hands it back.
    svc, repo = _service([_user(role=Role.TEACHER)])
    repo._by_id["user-1"] = replace(repo._by_id["user-1"], role=Role.SCHOOL_ADMIN)
    result = await svc.refresh(refresh_token="r:user-1")
    assert result.user.role is Role.SCHOOL_ADMIN


async def test_refresh_for_disabled_user_rejected() -> None:
    svc, _ = _service([_user(status=UserStatus.DISABLED)])
    with pytest.raises(AuthenticationError):
        await svc.refresh(refresh_token="r:user-1")


async def test_refresh_for_unknown_user_rejected() -> None:
    svc, _ = _service([_user()])
    with pytest.raises(AuthenticationError):
        await svc.refresh(refresh_token="r:ghost")


async def test_change_password_updates_and_clears_flag() -> None:
    svc, repo = _service([_user(must_change_password=True)])
    await svc.change_password(
        user_id="user-1", current_password="pw", new_password="brand-new-pw"
    )
    assert repo.set_calls == [("user-1", "hash:brand-new-pw", False)]


async def test_change_password_wrong_current_rejected() -> None:
    svc, repo = _service([_user()])
    with pytest.raises(AuthenticationError):
        await svc.change_password(
            user_id="user-1", current_password="wrong", new_password="brand-new-pw"
        )
    assert repo.set_calls == []
