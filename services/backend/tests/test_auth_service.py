"""AuthService use-cases with fakes (decisions/0024) — no crypto, no DB.

The service depends only on ports, so the shared fakes fully exercise login /
refresh / change-password without argon2 or PyJWT.
"""

from __future__ import annotations

import pytest
from backend.domain.errors import AuthenticationError
from backend.domain.models import Role, User, UserStatus
from backend.services.auth_service import AuthService
from backend_fakes import FakeHasher, FakeTokens, FakeUserRepo, make_user


def _service(
    users: list[User], *, needs_rehash: bool = False
) -> tuple[AuthService, FakeUserRepo]:
    repo = FakeUserRepo(users)
    svc = AuthService(repo, FakeHasher(needs_rehash=needs_rehash), FakeTokens())
    return svc, repo


async def test_login_success_returns_tokens_and_flag() -> None:
    svc, _ = _service([make_user(must_change_password=True)])
    result = await svc.login(email="t@x.io", password="pw")
    assert result.tokens.access_token == "a:user-1"
    assert result.user.must_change_password is True


async def test_login_wrong_password_is_generic_401() -> None:
    svc, _ = _service([make_user()])
    with pytest.raises(AuthenticationError):
        await svc.login(email="t@x.io", password="nope")


async def test_login_unknown_email_is_generic_401() -> None:
    # Missing user still runs a verify against the equalizer hash — no crash, no leak.
    svc, _ = _service([make_user()])
    with pytest.raises(AuthenticationError):
        await svc.login(email="ghost@x.io", password="pw")


async def test_login_disabled_user_rejected() -> None:
    svc, _ = _service([make_user(status=UserStatus.DISABLED)])
    with pytest.raises(AuthenticationError):
        await svc.login(email="t@x.io", password="pw")


async def test_login_rehashes_when_params_stale() -> None:
    svc, repo = _service([make_user(must_change_password=True)], needs_rehash=True)
    await svc.login(email="t@x.io", password="pw")
    # Re-hashed, preserving the must-change flag (not a password change).
    assert repo.set_calls == [("user-1", "hash:pw", True)]


async def test_refresh_success() -> None:
    svc, _ = _service([make_user()])
    result = await svc.refresh(refresh_token="r:user-1")
    assert result.tokens.refresh_token == "r:user-1"


async def test_refresh_reflects_role_change() -> None:
    # The reason refresh reloads identity (0024): a role/tenant change takes effect
    # on the next refresh, not at token expiry.
    svc, repo = _service([make_user(role=Role.TEACHER)])
    repo.mutate("user-1", role=Role.SCHOOL_ADMIN)
    result = await svc.refresh(refresh_token="r:user-1")
    assert result.user.role is Role.SCHOOL_ADMIN


async def test_refresh_for_disabled_user_rejected() -> None:
    svc, _ = _service([make_user(status=UserStatus.DISABLED)])
    with pytest.raises(AuthenticationError):
        await svc.refresh(refresh_token="r:user-1")


async def test_refresh_for_unknown_user_rejected() -> None:
    svc, _ = _service([make_user()])
    with pytest.raises(AuthenticationError):
        await svc.refresh(refresh_token="r:ghost")


async def test_change_password_updates_and_clears_flag() -> None:
    svc, repo = _service([make_user(must_change_password=True)])
    await svc.change_password(
        user_id="user-1", current_password="pw", new_password="brand-new-pw"
    )
    assert repo.set_calls == [("user-1", "hash:brand-new-pw", False)]


async def test_change_password_wrong_current_rejected() -> None:
    svc, repo = _service([make_user()])
    with pytest.raises(AuthenticationError):
        await svc.change_password(
            user_id="user-1", current_password="wrong", new_password="brand-new-pw"
        )
    assert repo.set_calls == []
