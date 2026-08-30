"""RBAC: the static resolver + the role→permission map (decisions/0024)."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.adapters.security.static_permissions import StaticPermissionResolver
from backend.domain.models import Role, User, UserStatus
from backend.domain.permissions import ROLE_PERMISSIONS, Permission


def _user(role: Role) -> User:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return User(
        id="u",
        school_id=None if role is Role.PLATFORM_ADMIN else "s",
        email="e@x.io",
        password_hash="h",
        role=role,
        status=UserStatus.ACTIVE,
        must_change_password=False,
        created_at=now,
        updated_at=now,
    )


def test_every_role_has_a_permission_set() -> None:
    for role in Role:
        assert role in ROLE_PERMISSIONS


def test_resolver_serves_the_role_map() -> None:
    resolver = StaticPermissionResolver()
    for role in Role:
        assert resolver.permissions_for(_user(role)) == ROLE_PERMISSIONS[role]


def test_platform_admin_manages_schools_only() -> None:
    perms = StaticPermissionResolver().permissions_for(_user(Role.PLATFORM_ADMIN))
    assert perms == frozenset({Permission.SCHOOL_MANAGE})


def test_student_is_scoped_to_own_gallery() -> None:
    perms = StaticPermissionResolver().permissions_for(_user(Role.STUDENT))
    assert Permission.GALLERY_VIEW_OWN in perms
    assert Permission.GALLERY_VIEW_ALL not in perms
    assert Permission.SCHOOL_MANAGE not in perms


def test_teacher_cannot_manage_staff() -> None:
    perms = StaticPermissionResolver().permissions_for(_user(Role.TEACHER))
    assert Permission.STAFF_MANAGE not in perms
    assert Permission.STUDENT_MANAGE in perms


def test_whatsapp_manage_is_school_admin_only() -> None:
    # W1: whatsapp:manage is granted to school_admin only (like audit:view / class:manage).
    resolver = StaticPermissionResolver()
    assert Permission.WHATSAPP_MANAGE in resolver.permissions_for(_user(Role.SCHOOL_ADMIN))
    for role in (Role.TEACHER, Role.STUDENT, Role.PLATFORM_ADMIN):
        assert Permission.WHATSAPP_MANAGE not in resolver.permissions_for(_user(role))


def test_whatsapp_send_is_admin_and_teacher() -> None:
    # W2: whatsapp:send is granted to school_admin AND teacher (mirrors notification:send).
    resolver = StaticPermissionResolver()
    assert Permission.WHATSAPP_SEND in resolver.permissions_for(_user(Role.SCHOOL_ADMIN))
    assert Permission.WHATSAPP_SEND in resolver.permissions_for(_user(Role.TEACHER))
    for role in (Role.STUDENT, Role.PLATFORM_ADMIN):
        assert Permission.WHATSAPP_SEND not in resolver.permissions_for(_user(role))
