"""Event category use-cases (BP11b, decisions/0059).

Pure orchestration over the `EventCategoryRepository` — no HTTP, no RBAC (authorization is at
the route: `event:manage`, admins + staff). The tenant (`school_id`) is the caller's token,
passed in by the route. Categories are per-school configurable: a school starts seeded with
`DEFAULT_EVENT_CATEGORIES`; admins/staff add more; removing one un-tags its events (SET NULL),
never deletes them.
"""

from __future__ import annotations

from backend.domain.errors import ConflictError, NotFoundError, ValidationError
from backend.domain.models import DEFAULT_EVENT_CATEGORIES, EventCategory
from backend.domain.ports import EventCategoryRepository

_MAX_NAME = 60


def _clean_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ValidationError("category name is required")
    if len(cleaned) > _MAX_NAME:
        raise ValidationError(f"category name too long (max {_MAX_NAME})")
    return cleaned


class EventCategoryService:
    def __init__(self, categories: EventCategoryRepository) -> None:
        self._categories = categories

    async def list_categories(self, *, school_id: str) -> list[EventCategory]:
        return await self._categories.list_by_school(school_id)

    async def add_category(self, *, school_id: str, name: str) -> EventCategory:
        clean = _clean_name(name)
        # Case-insensitive dedupe within the school (the DB UNIQUE is the second line).
        if await self._categories.get_by_name(school_id, clean) is not None:
            raise ConflictError(f"category already exists: {clean}")
        return await self._categories.create(school_id=school_id, name=clean)

    async def delete_category(self, *, school_id: str, category_id: str) -> None:
        if not await self._categories.delete(school_id, category_id):
            raise NotFoundError(f"category not found: {category_id}")

    async def seed_defaults(self, *, school_id: str) -> None:
        """Seed the default categories for a school (used on school-create)."""
        await self._categories.seed_defaults(school_id, DEFAULT_EVENT_CATEGORIES)
