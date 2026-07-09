"""Authentication use-cases — login, token refresh, password change.

Depends only on the `UserRepository`, `PasswordHasher`, and `TokenService` ports
(decisions/0024), so it imports no crypto library and is unit-testable with fakes
(the layering invariant, `tests/test_layering.py`). All credential failures raise the
same generic `AuthenticationError` so callers cannot enumerate accounts.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.domain.errors import AuthenticationError
from backend.domain.models import User, UserStatus
from backend.domain.ports import PasswordHasher, TokenService, UserRepository
from backend.domain.tokens import TokenPair, TokenType

# One message for every credential failure — no account enumeration.
_INVALID = "invalid email or password"


@dataclass(frozen=True, slots=True)
class LoginResult:
    tokens: TokenPair
    user: User


class AuthService:
    def __init__(
        self,
        users: UserRepository,
        hasher: PasswordHasher,
        tokens: TokenService,
    ) -> None:
        self._users = users
        self._hasher = hasher
        self._tokens = tokens
        self._dummy_hash: str | None = None

    async def login(self, *, email: str, password: str) -> LoginResult:
        user = await self._users.get_by_email(email)
        # Verify even when the user is missing/disabled, against a real hash, so the
        # response time does not betray whether the account exists (timing oracle).
        stored = user.password_hash if user is not None else self._equalizer_hash()
        ok = self._hasher.verify(password, stored)
        if user is None or user.status is not UserStatus.ACTIVE or not ok:
            raise AuthenticationError(_INVALID)
        await self._maybe_rehash(user, password)
        return LoginResult(tokens=self._tokens.issue_pair(user), user=user)

    async def refresh(self, *, refresh_token: str) -> LoginResult:
        claims = self._tokens.decode(refresh_token, expected_type=TokenType.REFRESH)
        user = await self._users.get(claims.subject)
        if user is None or user.status is not UserStatus.ACTIVE:
            raise AuthenticationError("refresh token no longer valid")
        return LoginResult(tokens=self._tokens.issue_pair(user), user=user)

    async def change_password(
        self, *, user_id: str, current_password: str, new_password: str
    ) -> None:
        user = await self._users.get(user_id)
        # The caller is already authenticated; a missing/disabled user here means the
        # account changed under them — treat as an auth failure, not a 404.
        if user is None or user.status is not UserStatus.ACTIVE:
            raise AuthenticationError(_INVALID)
        if not self._hasher.verify(current_password, user.password_hash):
            raise AuthenticationError("current password is incorrect")
        await self._users.set_password(
            user_id,
            password_hash=self._hasher.hash(new_password),
            must_change_password=False,
        )

    async def _maybe_rehash(self, user: User, password: str) -> None:
        """Transparently upgrade a stored hash whose parameters are out of date."""
        if self._hasher.needs_rehash(user.password_hash):
            await self._users.set_password(
                user.id,
                password_hash=self._hasher.hash(password),
                must_change_password=user.must_change_password,
            )

    def _equalizer_hash(self) -> str:
        """A real (memoized) hash to verify against on the user-not-found path, so
        that branch spends the same work as a genuine verify. This closes the
        *account-existence* oracle (does this email exist) — the one that matters.
        It does not equalize the rare rehash write on a valid login, which is a
        credential-validity signal only; not worth async-offloading here. Not a
        credential."""
        if self._dummy_hash is None:
            self._dummy_hash = self._hasher.hash("timing-equalizer")
        return self._dummy_hash
