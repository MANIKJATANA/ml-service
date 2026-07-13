"""Event routes (decisions/0027).

Event CRUD is gated on `event:manage`; **processing** an event (the "Process" /
"redistribute" button) on `media:upload`; reading its status on `job:status:view` — all
held by school_admin + teacher. Tenant isolation: the school is taken from the token
(`tenant_of`), never the URL/body — an `event_id` from another school resolves to 404.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from backend.api.deps import ContainerDep, require_permissions, tenant_of
from backend.api.schemas.events import (
    CreateEventRequest,
    EventListItem,
    EventResponse,
    UpdateEventRequest,
)
from backend.api.schemas.media import EventStatusResponse
from backend.api.schemas.notifications import (
    NotificationRosterResponse,
    NotifyResultResponse,
)
from backend.domain.models import User
from backend.domain.permissions import Permission

router = APIRouter(prefix="/v1/events", tags=["events"])

EventManager = Annotated[User, Depends(require_permissions(Permission.EVENT_MANAGE))]
MediaUploader = Annotated[User, Depends(require_permissions(Permission.MEDIA_UPLOAD))]
StatusViewer = Annotated[User, Depends(require_permissions(Permission.JOB_STATUS_VIEW))]
Notifier = Annotated[User, Depends(require_permissions(Permission.NOTIFICATION_SEND))]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=EventResponse)
async def create_event(
    body: CreateEventRequest, container: ContainerDep, actor: EventManager
) -> EventResponse:
    event = await container.event_service().create_event(
        school_id=tenant_of(actor),
        name=body.name,
        description=body.description,
        event_date=body.event_date,
        created_by=actor.id,
    )
    return EventResponse.from_event(event)


@router.get("", response_model=list[EventListItem])
async def list_events(
    container: ContainerDep, actor: EventManager
) -> list[EventListItem]:
    listings = await container.listing_service().list_events(school_id=tenant_of(actor))
    return [EventListItem.from_listing(x) for x in listings]


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: str, container: ContainerDep, actor: EventManager
) -> EventResponse:
    event = await container.event_service().get_event(
        school_id=tenant_of(actor), event_id=event_id
    )
    return EventResponse.from_event(event)


@router.patch("/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: str,
    body: UpdateEventRequest,
    container: ContainerDep,
    actor: EventManager,
) -> EventResponse:
    event = await container.event_service().update_event(
        school_id=tenant_of(actor),
        event_id=event_id,
        name=body.name,
        description=body.description,
        event_date=body.event_date,
        status=body.status,
        auto_notify=body.auto_notify,
    )
    return EventResponse.from_event(event)


@router.post("/{event_id}/process", response_model=EventResponse)
async def process_event(
    event_id: str, container: ContainerDep, actor: MediaUploader
) -> EventResponse:
    """Enqueue one event-level inference job. Pressing again redistributes leftovers."""
    event = await container.event_service().process_event(
        school_id=tenant_of(actor), event_id=event_id
    )
    return EventResponse.from_event(event)


@router.get("/{event_id}/status", response_model=EventStatusResponse)
async def event_status(
    event_id: str, container: ContainerDep, actor: StatusViewer
) -> EventStatusResponse:
    view = await container.event_service().event_status(
        school_id=tenant_of(actor), event_id=event_id
    )
    return EventStatusResponse.from_view(view)


@router.post("/{event_id}/notify", response_model=NotifyResultResponse)
async def notify_students(
    event_id: str, container: ContainerDep, actor: Notifier
) -> NotifyResultResponse:
    """Announce a completed event's photos to the students in them + fan out to the
    configured channels. 400 if archived / not yet finished processing."""
    notified = await container.notification_service().notify_event(
        school_id=tenant_of(actor), event_id=event_id
    )
    return NotifyResultResponse(notified=notified)


@router.get("/{event_id}/notifications", response_model=NotificationRosterResponse)
async def notification_roster(
    event_id: str, container: ContainerDep, actor: Notifier
) -> NotificationRosterResponse:
    """Who's been notified about this event + who has opened their photos."""
    roster = await container.notification_service().event_roster(
        school_id=tenant_of(actor), event_id=event_id
    )
    return NotificationRosterResponse.from_roster(roster)
