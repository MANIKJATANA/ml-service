"""Composition root — builds concrete adapters from settings and injects them
(mirrors the ML service's ``wiring/container.py``).

One of the few layers allowed to import adapters. It reads each ``settings.*_impl``
selector, resolves the class via :mod:`wiring.registry`, and constructs it. Adapters
are built once and memoized: the DB engine/sessionmaker is shared across repositories.
Nothing is built until first requested. Secrets (the DB password in the DSN) come
from ``settings`` (the environment) and are never stored in code.

The surface grows per phase; Phase 1 wires the DB sessionmaker and the two identity
repositories, plus the ``/readyz`` probe and shutdown disposal.
"""

from __future__ import annotations

import asyncio
import threading

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backend.db.session import make_engine, make_sessionmaker
from backend.domain.ports import (
    PasswordHasher,
    PermissionResolver,
    SchoolRepository,
    TokenService,
    UserRepository,
)
from backend.services.auth_service import AuthService
from backend.settings import Settings
from backend.wiring import registry


class Container:
    """Lazily builds and memoizes adapters from ``Settings``."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings
        # FastAPI resolves cold concurrent requests in parallel; serialize the lazy
        # builders so a resource is constructed once. Reentrant on purpose.
        self._lock = threading.RLock()
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None
        self._school_repo: SchoolRepository | None = None
        self._user_repo: UserRepository | None = None
        self._password_hasher: PasswordHasher | None = None
        self._token_service: TokenService | None = None
        self._permission_resolver: PermissionResolver | None = None
        self._auth_service: AuthService | None = None

    # ---- shared resources ----------------------------------------------

    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        if self._sessionmaker is None:
            with self._lock:
                if self._sessionmaker is None:
                    self._engine = make_engine(
                        self._s.database_url, echo=self._s.db_echo
                    )
                    self._sessionmaker = make_sessionmaker(self._engine)
        return self._sessionmaker

    # ---- adapters (one memoized instance each) -------------------------

    def school_repo(self) -> SchoolRepository:
        if self._school_repo is None:
            with self._lock:
                if self._school_repo is None:
                    cls = registry.resolve(
                        registry.SCHOOL_REPO_REGISTRY, self._s.repository_impl
                    )
                    self._school_repo = cls(self.sessionmaker())
        return self._school_repo

    def user_repo(self) -> UserRepository:
        if self._user_repo is None:
            with self._lock:
                if self._user_repo is None:
                    cls = registry.resolve(
                        registry.USER_REPO_REGISTRY, self._s.repository_impl
                    )
                    self._user_repo = cls(self.sessionmaker())
        return self._user_repo

    # ---- auth (decisions/0024) -----------------------------------------

    def password_hasher(self) -> PasswordHasher:
        if self._password_hasher is None:
            with self._lock:
                if self._password_hasher is None:
                    cls = registry.resolve(
                        registry.PASSWORD_HASHER_REGISTRY, self._s.password_hasher_impl
                    )
                    self._password_hasher = cls()
        return self._password_hasher

    def token_service(self) -> TokenService:
        if self._token_service is None:
            with self._lock:
                if self._token_service is None:
                    cls = registry.resolve(
                        registry.TOKEN_SERVICE_REGISTRY, self._s.token_service_impl
                    )
                    # Fails loud here if BE_JWT_SECRET is empty (decisions/0024).
                    self._token_service = cls(
                        secret=self._s.jwt_secret.get_secret_value(),
                        algorithm=self._s.jwt_algorithm,
                        issuer=self._s.jwt_issuer,
                        access_ttl_s=self._s.access_token_ttl_s,
                        refresh_ttl_s=self._s.refresh_token_ttl_s,
                    )
        return self._token_service

    def permission_resolver(self) -> PermissionResolver:
        if self._permission_resolver is None:
            with self._lock:
                if self._permission_resolver is None:
                    cls = registry.resolve(
                        registry.PERMISSION_RESOLVER_REGISTRY,
                        self._s.permission_resolver_impl,
                    )
                    self._permission_resolver = cls()
        return self._permission_resolver

    def auth_service(self) -> AuthService:
        if self._auth_service is None:
            with self._lock:
                if self._auth_service is None:
                    self._auth_service = AuthService(
                        self.user_repo(),
                        self.password_hasher(),
                        self.token_service(),
                    )
        return self._auth_service

    # ---- lifecycle -----------------------------------------------------

    async def check_readiness(self) -> dict[str, bool]:
        """Best-effort probe of the configured infra deps for ``/readyz``.

        Pings Postgres when a postgres repo is selected. Returns a per-dependency
        ok/not-ok map; an empty map means nothing to check.
        """
        from sqlalchemy import text

        checks: dict[str, bool] = {}
        if self._s.repository_impl == "postgres":
            try:
                async with asyncio.timeout(self._s.readiness_timeout_s):
                    async with self.sessionmaker()() as session:
                        await session.execute(text("SELECT 1"))
                checks["database"] = True
            except Exception:  # unreachable/slow/down -> not ready (bounded)
                checks["database"] = False
        return checks

    async def aclose(self) -> None:
        """Dispose shared resources. Safe to call once at shutdown."""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._sessionmaker = None
