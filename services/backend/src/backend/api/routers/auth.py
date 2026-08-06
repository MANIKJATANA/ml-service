"""Auth routes: login, refresh, change-password, me (decisions/0024).

Thin edge layer — parse/validate the request, delegate to `AuthService`, shape the
response. Domain errors (`AuthenticationError` → 401, etc.) are mapped centrally in
`main.py`, so handlers here stay happy-path.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from backend.api.deps import ContainerDep, CurrentUser
from backend.api.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
)
from backend.api.schemas.users import UserResponse
from backend.domain.models import Role

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, container: ContainerDep) -> TokenResponse:
    result = await container.auth_service().login(
        email=body.email, password=body.password
    )
    return TokenResponse.from_pair(
        result.tokens, must_change_password=result.user.must_change_password
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, container: ContainerDep) -> TokenResponse:
    result = await container.auth_service().refresh(refresh_token=body.refresh_token)
    return TokenResponse.from_pair(
        result.tokens, must_change_password=result.user.must_change_password
    )


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest, user: CurrentUser, container: ContainerDep
) -> Response:
    await container.auth_service().change_password(
        user_id=user.id,
        current_password=body.current_password,
        new_password=body.new_password,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser, container: ContainerDep) -> UserResponse:
    # BP18b: surface the student's display name on /me (the shell shows it). The name lives on
    # the students profile, not the users row, so resolve it for a student; staff/platform have
    # no name (null), and a student with no profile row (orphan login) also yields null — never
    # a 500. Tenant-safe: the lookup is scoped to the user's own school + user_id.
    name: str | None = None
    if user.role is Role.STUDENT and user.school_id is not None:
        student = await container.student_repo().get_by_user_id(user.school_id, user.id)
        name = student.name if student is not None else None
    return UserResponse.from_user(user, name=name)
