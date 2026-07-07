"""Backend ports — the Protocol interfaces the services depend on.

Concrete implementations live under ``adapters/`` and are selected by config via
``wiring/registry.py`` (decisions/0022). Keeping services import-pure against these
Protocols (no SQLAlchemy/httpx/redis/supabase) is enforced by
``tests/test_layering.py``. The surface grows per phase; Phase 1 defines only the
repositories for the two identity tables.
"""

from __future__ import annotations

from typing import Protocol

from backend.domain.models import Role, School, User


class SchoolRepository(Protocol):
    async def create(self, *, name: str, max_teachers: int) -> School: ...
    async def get(self, school_id: str) -> School | None: ...
    async def list_all(self) -> list[School]: ...


class UserRepository(Protocol):
    async def create(
        self, *, school_id: str | None, email: str, password_hash: str, role: Role
    ) -> User: ...
    async def get(self, user_id: str) -> User | None: ...
    async def get_by_email(self, email: str) -> User | None: ...
