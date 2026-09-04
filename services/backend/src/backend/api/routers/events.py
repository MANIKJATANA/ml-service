"""Event routes (decisions/0027).

Event CRUD is gated on `event:manage`; **processing** an event (the "Process" /
"redistribute" button) on `media:upload`; reading its status on `job:status:view` — all
held by school_admin + teacher. Tenant isolation: the school is taken from the token
(`tenant_of`), never the URL/body — an `event_id` from another school resolves to 404.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from backend.api.deps import (
    ContainerDep,
    require_permissions,
    resolve_focus_group_ids,
    tenant_of,
)
from backend.api.pagination import (
    DEFAULT_PAGE_SIZE,
    LimitQuery,
    OffsetQuery,
    SearchQuery,
    is_descending,
)
from backend.api.schemas.events import (
    BulkEventStatusRequest,
    BulkEventStatusResponse,
    CreateEventRequest,
    EventListPageResponse,
    EventResponse,
    EventTermsResponse,
    UpdateEventRequest,
)
from backend.api.schemas.media import EventStatusResponse
from backend.api.schemas.notifications import (
    NotificationRosterResponse,
    NotifyResultResponse,
)
from backend.api.schemas.whatsapp import (
    EventPhotoRecipientResponse,
    EventPhotoRecipientsRequest,
    EventPhotoRecipientsResponse,
    EventPhotoSendRequest,
    EventPhotoSendResponse,
)
from backend.domain.models import UNSET, EventSort, EventStatus, SortDir, User
from backend.domain.permissions import Permission

router = APIRouter(prefix="/v1/events", tags=["events"])

EventManager = Annotated[User, Depends(require_permissions(Permission.EVENT_MANAGE))]
MediaUploader = Annotated[User, Depends(require_permissions(Permission.MEDIA_UPLOAD))]
StatusViewer = Annotated[User, Depends(require_permissions(Permission.JOB_STATUS_VIEW))]
Notifier = Annotated[User, Depends(require_permissions(Permission.NOTIFICATION_SEND))]
WhatsAppSendManager = Annotated[
    User, Depends(require_permissions(Permission.WHATSAPP_SEND))
]


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
        category_id=body.category_id,
        term=body.term,
        student_group_id=body.student_group_id,
    )
    return EventResponse.from_event(event)


@router.get("", response_model=EventListPageResponse)
async def list_events(
    container: ContainerDep,
    actor: EventManager,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    offset: OffsetQuery = 0,
    q: SearchQuery = None,
    sort: Annotated[EventSort, Query()] = EventSort.EVENT_DATE,
    dir: Annotated[SortDir, Query()] = SortDir.DESC,
    status: Annotated[EventStatus | None, Query()] = None,
    category_id: Annotated[str | None, Query(max_length=64)] = None,
    term: Annotated[str | None, Query(max_length=100)] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    student_group_id: Annotated[str | None, Query(max_length=64)] = None,
    mine: Annotated[bool, Query()] = False,
) -> EventListPageResponse:
    """One page of the events list (BP9): server search (name), sort (incl. the whole-list
    media/matched/needs-review count columns), lifecycle-status filter, and (BP11b) category /
    term / an ``event_date`` range (the calendar's month window). BP11c: ``student_group_id``
    filters to one class; ``mine=true`` limits a teacher's list to their classes' events (+
    untagged school-wide events) — ignored for an admin."""
    scope = await resolve_focus_group_ids(container, actor, mine)
    page = await container.listing_service().list_events_page(
        school_id=tenant_of(actor),
        limit=limit,
        offset=offset,
        q=q,
        sort=sort,
        descending=is_descending(dir),
        status=status,
        category_id=category_id,
        term=term,
        date_from=date_from,
        date_to=date_to,
        student_group_id=student_group_id,
        scope_group_ids=scope,
    )
    return EventListPageResponse.from_page(page)


@router.get("/terms", response_model=EventTermsResponse)
async def list_terms(
    container: ContainerDep, actor: EventManager
) -> EventTermsResponse:
    """The distinct terms this school has used (BP11b — feeds the term filter dropdown).
    Registered before ``/{event_id}`` so the literal wins the route match."""
    terms = await container.event_service().list_terms(school_id=tenant_of(actor))
    return EventTermsResponse(terms=terms)


@router.post("/bulk-status", response_model=BulkEventStatusResponse)
async def bulk_event_status(
    body: BulkEventStatusRequest, container: ContainerDep, actor: EventManager
) -> BulkEventStatusResponse:
    """Archive/restore many events at once (BP13). Tenant from the token; a foreign id is
    silently skipped. Registered before ``/{event_id}`` so the literal wins the route match."""
    updated = await container.event_service().set_status_bulk(
        school_id=tenant_of(actor), event_ids=body.event_ids, status=body.status
    )
    return BulkEventStatusResponse(updated=updated)


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: str, container: ContainerDep, actor: EventManager
) -> EventResponse:
    detail = await container.event_service().get_event_detail(
        school_id=tenant_of(actor), event_id=event_id
    )
    return EventResponse.from_event(
        detail.event, created_by_email=detail.created_by_email
    )


@router.patch("/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: str,
    body: UpdateEventRequest,
    container: ContainerDep,
    actor: EventManager,
) -> EventResponse:
    # BP24: the three TAG fields are tri-state — a field the caller OMITTED passes UNSET
    # (leave unchanged); a field present in the body (a value OR an explicit null) passes
    # through, so an explicit null clears it. Pydantic v2 ``model_fields_set`` tells them apart.
    provided = body.model_fields_set
    event = await container.event_service().update_event(
        school_id=tenant_of(actor),
        event_id=event_id,
        name=body.name,
        description=body.description,
        event_date=body.event_date,
        status=body.status,
        auto_notify=body.auto_notify,
        category_id=body.category_id if "category_id" in provided else UNSET,
        term=body.term if "term" in provided else UNSET,
        student_group_id=(
            body.student_group_id if "student_group_id" in provided else UNSET
        ),
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


@router.post(
    "/{event_id}/photo-recipients", response_model=EventPhotoRecipientsResponse
)
async def event_photo_recipients(
    event_id: str,
    body: EventPhotoRecipientsRequest,
    container: ContainerDep,
    actor: WhatsAppSendManager,
) -> EventPhotoRecipientsResponse:
    """Pre-send preview for the event-photo fan-out: for the SELECTED photos, who effectively
    appears in them (BP5 overlay — rejected excluded), how many each, and whether they can
    receive (opted in + a number). Requires ``whatsapp:send``; tenant from the token (a foreign
    event/media contributes nothing). Sends NOTHING — the FE confirms before the send."""
    recipients = await container.gallery_service().event_photo_recipients(
        school_id=tenant_of(actor), event_id=event_id, media_ids=body.media_ids
    )
    # Interim test mode (a platform interim number is set) diverts every send to the test number
    # regardless of consent — surface it so the FE enables the send even with no opted-in student.
    platform = await container.platform_config_service().get_config()
    return EventPhotoRecipientsResponse(
        recipients=[
            EventPhotoRecipientResponse(
                student_id=s.id,
                name=s.name,
                photo_count=len(ids),
                opted_in=s.whatsapp_opt_in,
                has_number=s.mobile_number is not None,
            )
            for s, ids in recipients
        ],
        interim=bool(platform.interim_test_number),
    )


@router.post(
    "/{event_id}/whatsapp-send-photos", response_model=EventPhotoSendResponse
)
async def send_event_photos(
    event_id: str,
    body: EventPhotoSendRequest,
    container: ContainerDep,
    actor: WhatsAppSendManager,
) -> EventPhotoSendResponse:
    """Fan out the SELECTED event photos to the students who appear in them — each gets the
    subset they effectively appear in (BP5 overlay). Reuses the fully-gated per-student send
    (consent + budget + effective intersection + interim + PII); a non-consenting student is
    skipped, never aborting the fan-out. Requires ``whatsapp:send``; tenant from the token. 400
    if WhatsApp isn't configured. PII-free (no recipient number in the response)."""
    summary = await container.whatsapp_share_service().send_event_photos(
        school_id=tenant_of(actor),
        event_id=event_id,
        media_ids=body.media_ids,
        actor_user_id=actor.id,
        actor_role=actor.role.value,
    )
    return EventPhotoSendResponse.from_summary(summary)
