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
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.deps import get_container
from backend.domain.errors import AuthenticationError, AuthorizationError
from backend.domain.models import Role, User, UserStatus
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
    # BP18d: a password change/reset bumps the user's token_version — reject any token minted
    # before it (revokes all older sessions on the next request).
    if claims.token_version != user.token_version:
        raise AuthenticationError("session expired; please sign in again")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def tenant_of(user: User) -> str:
    """The caller's school for a school-scoped route — from the token, never the URL.

    Non-platform roles always have a school (DB CHECK); fail closed anyway so a
    school-scoped route never proceeds without a tenant (decisions/0025, 0026)."""
    if user.school_id is None:
        raise AuthorizationError("account is not scoped to a school")
    return user.school_id


async def resolve_focus_group_ids(
    container: Container, actor: User, mine: bool
) -> list[str] | None:
    """A teacher's list "focus" scope (BP11c, decisions/0060): the class ids their students/
    events lists limit to when ``mine=true``.

    Returns ``None`` (no scoping — the full school) unless the caller is a **teacher** who asked
    for ``mine`` — then their assigned class ids (possibly ``[]``, a teacher with no classes).
    An admin's ``mine`` is ignored (they see everything); this never widens access — focus is a
    convenience default over what the caller could already reach, not a hard boundary."""
    if not mine or actor.role is not Role.TEACHER:
        return None
    return await container.delegation_service().my_group_ids(
        school_id=tenant_of(actor), teacher_id=actor.id
    )


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


@dataclass(frozen=True, slots=True)
class GalleryScope:
    """A gallery caller's tenant + optional own-only restriction (decisions/0028).

    ``restrict_to_student_id=None`` -> staff (all the school's media). Otherwise the
    caller is a student limited to the media/events they appear in."""

    school_id: str
    restrict_to_student_id: str | None


async def _student_scope(container: Container, user: User) -> GalleryScope:
    """Resolve a logged-in student to a scope bound to their own ``student_id``."""
    school_id = tenant_of(user)
    student = await container.student_repo().get_by_user_id(school_id, user.id)
    if student is None:
        raise AuthorizationError("no student profile for this account")
    return GalleryScope(school_id=school_id, restrict_to_student_id=student.id)


async def resolve_gallery_download_scope(
    container: ContainerDep, user: CurrentUser
) -> GalleryScope:
    """Download authz (decisions/0028): a caller with ``gallery:view_all`` (staff) may
    download any media in their school; one with ``gallery:view_own`` (student) is
    restricted to media they appear in. Anyone else is refused."""
    granted = container.permission_resolver().permissions_for(user)
    if Permission.GALLERY_VIEW_ALL in granted:
        return GalleryScope(school_id=tenant_of(user), restrict_to_student_id=None)
    if Permission.GALLERY_VIEW_OWN in granted:
        return await _student_scope(container, user)
    raise AuthorizationError("insufficient permissions")


async def resolve_student_self_scope(
    container: ContainerDep, user: CurrentUser
) -> GalleryScope:
    """The ``/me`` gallery (decisions/0028): the caller must be a student
    (``gallery:view_own``); yields a scope bound to their own ``student_id``."""
    granted = container.permission_resolver().permissions_for(user)
    if Permission.GALLERY_VIEW_OWN not in granted:
        raise AuthorizationError("insufficient permissions")
    return await _student_scope(container, user)


GalleryDownloadScope = Annotated[
    GalleryScope, Depends(resolve_gallery_download_scope)
]
StudentSelfScope = Annotated[GalleryScope, Depends(resolve_student_self_scope)]
