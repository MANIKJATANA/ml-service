"""Static RBAC resolver — serves the hardcoded `ROLE_PERMISSIONS` map.

Implements the `PermissionResolver` port (decisions/0024). v1 policy is fixed in
`domain/permissions.py`; a later `DbPermissionResolver` will overlay per-school
override rows behind this same port with no change at any call site.
"""

from __future__ import annotations

from backend.domain.models import User
from backend.domain.permissions import ROLE_PERMISSIONS, Permission


class StaticPermissionResolver:
    def permissions_for(self, user: User) -> frozenset[Permission]:
        return ROLE_PERMISSIONS.get(user.role, frozenset())
