"""End-to-end auth routes over HTTP (decisions/0024).

Uses the real JWT + argon2 adapters and a fake user repository injected via a
`Container` subclass + ``dependency_overrides`` — no database. A throwaway
permission-gated route exercises ``require_permissions``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Annotated

from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep, require_permissions
from backend.domain.errors import NotFoundError
from backend.domain.models import Role, User, UserStatus
from backend.domain.permissions import Permission
from backend.domain.ports import UserRepository
from backend.main import create_app
from backend.settings import Settings
from backend.wiring.container import Container
from fastapi import Depends
from fastapi.testclient import TestClient
from pydantic import SecretStr

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_HASHER = Argon2PasswordHasher()


def _user(*, id: str, role: Role, password: str, school_id: str | None) -> User:
    return User(
        id=id,
        school_id=school_id,
        email=f"{id}@x.io",
        password_hash=_HASHER.hash(password),
        role=role,
        status=UserStatus.ACTIVE,
        must_change_password=False,
        created_at=_NOW,
        updated_at=_NOW,
    )


class FakeUserRepo:
    def __init__(self, users: list[User]) -> None:
        self._by_email = {u.email: u for u in users}
        self._by_id = {u.id: u for u in users}

    async def create(
        self,
        *,
        school_id: str | None,
        email: str,
        password_hash: str,
        role: Role,
        must_change_password: bool = False,
    ) -> User:  # pragma: no cover - unused
        raise NotImplementedError

    async def get(self, user_id: str) -> User | None:
        return self._by_id.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        return self._by_email.get(email)

    async def set_password(
        self, user_id: str, *, password_hash: str, must_change_password: bool
    ) -> None:
        user = self._by_id.get(user_id)
        if user is None:
            raise NotFoundError(user_id)
        self.mutate(user_id, password_hash=password_hash, must_change_password=must_change_password)

    def mutate(self, user_id: str, **changes: object) -> None:
        """Test helper: replace a stored user's fields (simulate out-of-band change)."""
        user = self._by_id[user_id]
        updated = replace(user, **changes)  # type: ignore[arg-type]
        self._by_id[user_id] = updated
        self._by_email[user.email] = updated


class _SeededContainer(Container):
    """Container with a pre-seeded user repo; JWT/argon2/RBAC stay real."""

    def __init__(self, settings: Settings, repo: UserRepository) -> None:
        super().__init__(settings)
        self._seed_repo = repo

    def user_repo(self) -> UserRepository:
        return self._seed_repo


def _build(users: list[User]) -> tuple[TestClient, FakeUserRepo]:
    repo = FakeUserRepo(users)
    container = _SeededContainer(
        Settings(jwt_secret=SecretStr("test-signing-key-0123456789abcdef0123")), repo
    )
    app = create_app()

    @app.get("/_admin_only")
    async def _admin_only(
        _: Annotated[User, Depends(require_permissions(Permission.SCHOOL_MANAGE))],
    ) -> dict[str, bool]:
        return {"ok": True}

    app.dependency_overrides[get_container_dep] = lambda: container
    return TestClient(app), repo


def _client(users: list[User]) -> TestClient:
    return _build(users)[0]


def _login(client: TestClient, email: str, password: str) -> dict[str, object]:
    resp = client.post("/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    body: dict[str, object] = resp.json()
    return body


def test_login_me_roundtrip() -> None:
    client = _client([_user(id="u1", role=Role.TEACHER, password="pw", school_id="s1")])
    body = _login(client, "u1@x.io", "pw")
    assert body["token_type"] == "bearer"
    assert body["must_change_password"] is False

    token = body["access_token"]
    me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "u1@x.io"
    assert "password_hash" not in me.json()


def test_login_wrong_password_is_401() -> None:
    client = _client([_user(id="u1", role=Role.TEACHER, password="pw", school_id="s1")])
    resp = client.post("/v1/auth/login", json={"email": "u1@x.io", "password": "nope"})
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


def test_login_unknown_email_is_401() -> None:
    client = _client([_user(id="u1", role=Role.TEACHER, password="pw", school_id="s1")])
    resp = client.post("/v1/auth/login", json={"email": "ghost@x.io", "password": "pw"})
    assert resp.status_code == 401


def test_me_requires_a_token() -> None:
    client = _client([_user(id="u1", role=Role.TEACHER, password="pw", school_id="s1")])
    missing = client.get("/v1/auth/me")
    assert missing.status_code == 401
    assert missing.headers.get("WWW-Authenticate") == "Bearer"
    bad = client.get("/v1/auth/me", headers={"Authorization": "Bearer garbage"})
    assert bad.status_code == 401


def test_disabled_user_loses_access_with_a_still_valid_token() -> None:
    # The security reason get_current_user reloads on every request (0024): a token
    # issued while ACTIVE must stop working the moment the account is disabled.
    client, repo = _build(
        [_user(id="u1", role=Role.TEACHER, password="pw", school_id="s1")]
    )
    token = _login(client, "u1@x.io", "pw")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/v1/auth/me", headers=headers).status_code == 200

    repo.mutate("u1", status=UserStatus.DISABLED)
    resp = client.get("/v1/auth/me", headers=headers)
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


def test_me_for_platform_admin_has_null_school() -> None:
    client = _client(
        [_user(id="adm", role=Role.PLATFORM_ADMIN, password="pw", school_id=None)]
    )
    token = _login(client, "adm@x.io", "pw")["access_token"]
    body = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["role"] == "platform_admin" and body["school_id"] is None


def test_refresh_issues_new_tokens() -> None:
    client = _client([_user(id="u1", role=Role.TEACHER, password="pw", school_id="s1")])
    refresh = _login(client, "u1@x.io", "pw")["refresh_token"]
    resp = client.post("/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 200
    assert resp.json()["access_token"]

    # An access token may not be used on the refresh route.
    access = _login(client, "u1@x.io", "pw")["access_token"]
    assert client.post("/v1/auth/refresh", json={"refresh_token": access}).status_code == 401


def test_change_password_flow() -> None:
    client = _client([_user(id="u1", role=Role.TEACHER, password="pw", school_id="s1")])
    token = _login(client, "u1@x.io", "pw")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        "/v1/auth/change-password",
        json={"current_password": "pw", "new_password": "a-brand-new-pw"},
        headers=headers,
    )
    assert resp.status_code == 204

    # Old password no longer works; the new one does.
    assert client.post(
        "/v1/auth/login", json={"email": "u1@x.io", "password": "pw"}
    ).status_code == 401
    _login(client, "u1@x.io", "a-brand-new-pw")


def test_change_password_wrong_current_is_401() -> None:
    client = _client([_user(id="u1", role=Role.TEACHER, password="pw", school_id="s1")])
    token = _login(client, "u1@x.io", "pw")["access_token"]
    resp = client.post(
        "/v1/auth/change-password",
        json={"current_password": "wrong", "new_password": "a-brand-new-pw"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


def test_require_permissions_enforced() -> None:
    client = _client(
        [
            _user(id="adm", role=Role.PLATFORM_ADMIN, password="pw", school_id=None),
            _user(id="stu", role=Role.STUDENT, password="pw", school_id="s1"),
        ]
    )
    admin_token = _login(client, "adm@x.io", "pw")["access_token"]
    student_token = _login(client, "stu@x.io", "pw")["access_token"]

    ok = client.get("/_admin_only", headers={"Authorization": f"Bearer {admin_token}"})
    assert ok.status_code == 200

    forbidden = client.get(
        "/_admin_only", headers={"Authorization": f"Bearer {student_token}"}
    )
    assert forbidden.status_code == 403


def test_short_new_password_rejected_by_validation() -> None:
    client = _client([_user(id="u1", role=Role.TEACHER, password="pw", school_id="s1")])
    token = _login(client, "u1@x.io", "pw")["access_token"]
    resp = client.post(
        "/v1/auth/change-password",
        json={"current_password": "pw", "new_password": "short"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422  # pydantic min_length


def test_over_long_password_rejected_at_the_edge() -> None:
    # Guards against unbounded argon2 input (CPU-DoS); capped in the schema (0024).
    client = _client([_user(id="u1", role=Role.TEACHER, password="pw", school_id="s1")])
    resp = client.post(
        "/v1/auth/login", json={"email": "u1@x.io", "password": "x" * 5000}
    )
    assert resp.status_code == 422
