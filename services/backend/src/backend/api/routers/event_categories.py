"""Event category routes (BP11b, decisions/0059).

Tenant-configurable event categories: list / add / remove. Gated on `event:manage` — the same
school admins + staff who manage events (no new permission). Tenant is taken from the token,
never the URL/body; a foreign category resolves to 404.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from backend.api.deps import ContainerDep, require_permissions, tenant_of
from backend.api.schemas.events import (
    CreateEventCategoryRequest,
    EventCategoryResponse,
)
from backend.domain.models import User
from backend.domain.permissions import Permission

router = APIRouter(prefix="/v1/event-categories", tags=["event-categories"])

EventManager = Annotated[User, Depends(require_permissions(Permission.EVENT_MANAGE))]


@router.get("", response_model=list[EventCategoryResponse])
async def list_categories(
    container: ContainerDep, actor: EventManager
) -> list[EventCategoryResponse]:
    """Every category in the school (bounded — unpaginated). Feeds the filter + the picker."""
    cats = await container.event_category_service().list_categories(
        school_id=tenant_of(actor)
    )
    return [EventCategoryResponse.from_category(c) for c in cats]


@router.post(
    "", status_code=status.HTTP_201_CREATED, response_model=EventCategoryResponse
)
async def add_category(
    body: CreateEventCategoryRequest, container: ContainerDep, actor: EventManager
) -> EventCategoryResponse:
    """Add a category. A duplicate name (case-insensitive) in the school → 409."""
    cat = await container.event_category_service().add_category(
        school_id=tenant_of(actor), name=body.name
    )
    return EventCategoryResponse.from_category(cat)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: str, container: ContainerDep, actor: EventManager
) -> None:
    """Delete a category. Its events are un-tagged (SET NULL), never deleted; a foreign/unknown
    category → 404."""
    await container.event_category_service().delete_category(
        school_id=tenant_of(actor), category_id=category_id
    )
