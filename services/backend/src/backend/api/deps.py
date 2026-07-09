"""Request-scoped auth dependencies (decisions/0024).

`get_container_dep` exposes the process-wide composition root as a FastAPI
dependency, so tests can swap it via ``app.dependency_overrides``.
`get_current_user` authenticates the bearer access token and reloads the account
(so a disabled/deleted user loses access immediately, and role/tenant are always
fresh). `require_permissions(...)` is a dependency factory feature routers mount to
gate a route on the RBAC seam. Everything resolves through the container, which works
under a bare `TestClient` without the lifespan — matching health/readyz.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.deps import get_container
from backend.domain.errors import AuthenticationError, AuthorizationError
from backend.domain.models import User, UserStatus
from backend.domain.permissions import Permission
from backend.domain.tokens import TokenType
from backend.wiring.container import Container

# auto_error=False -> a missing/blank header yields None (we raise our own domain
# error → 401 with a WWW-Authenticate header), instead of FastAPI's bare 403.
_bearer = HTTPBearer(auto_error=False)


def get_container_dep() -> Container:
    """The composition root as an overridable dependency."""
    return get_container()


ContainerDep = Annotated[Container, Depends(get_container_dep)]


async def get_current_user(
    container: ContainerDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise AuthenticationError("missing bearer token")
    claims = container.token_service().decode(
        credentials.credentials, expected_type=TokenType.ACCESS
    )
    user = await container.user_repo().get(claims.subject)
    if user is None or user.status is not UserStatus.ACTIVE:
        raise AuthenticationError("account is not active")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def tenant_of(user: User) -> str:
    """The caller's school for a school-scoped route — from the token, never the URL.

    Non-platform roles always have a school (DB CHECK); fail closed anyway so a
    school-scoped route never proceeds without a tenant (decisions/0025, 0026)."""
    if user.school_id is None:
        raise AuthorizationError("account is not scoped to a school")
    return user.school_id


def require_permissions(
    *required: Permission,
) -> Callable[..., Awaitable[User]]:
    """Return a dependency that admits only callers granted every ``required`` perm."""

    async def guard(user: CurrentUser, container: ContainerDep) -> User:
        granted = container.permission_resolver().permissions_for(user)
        if not set(required).issubset(granted):
            raise AuthorizationError("insufficient permissions")
        return user

    return guard
