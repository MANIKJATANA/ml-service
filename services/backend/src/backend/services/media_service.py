"""Event-photo use-cases — upload URL, register, reads (decisions/0027).

Depends only on ports (no HTTP, no RBAC): authorization is at the route via
`require_permissions(media:upload | job:status:view)` and the tenant is the caller's
token `school_id`, never the URL/body. The photo bytes never pass through the backend —
the frontend uploads to Supabase via the signed URL, then registers the object path.

**Registering a photo enqueues nothing.** Processing is event-level: the "Process"
button (`EventService.process_event`) enqueues one job for the whole event.
"""

from __future__ import annotations

import uuid

from backend.domain.errors import NotFoundError, ValidationError
from backend.domain.models import Event, EventStatus, Media, MediaType, SignedUpload
from backend.domain.ports import EventRepository, MediaRepository, ObjectStore


class MediaService:
    def __init__(
        self,
        media: MediaRepository,
        events: EventRepository,
        object_store: ObjectStore,
        *,
        event_media_prefix: str,
    ) -> None:
        self._media = media
        self._events = events
        self._object_store = object_store
        self._prefix = event_media_prefix.strip("/")

    # ---- upload URL -----------------------------------------------------

    def _event_prefix(self, school_id: str, event_id: str) -> str:
        return f"{self._prefix}/{school_id}/{event_id}/"

    async def create_upload_url(
        self, *, school_id: str, event_id: str
    ) -> SignedUpload:
        # Verify the event is the caller's + active before minting a key under it.
        await self._require_active_event(school_id=school_id, event_id=event_id)
        object_path = f"{self._event_prefix(school_id, event_id)}{uuid.uuid4()}"
        return await self._object_store.create_signed_upload_url(object_path)

    # ---- register (records only; no enqueue) ---------------------------

    async def register_media(
        self,
        *,
        school_id: str,
        event_id: str,
        storage_path: str,
        media_type: MediaType,
    ) -> Media:
        await self._require_active_event(school_id=school_id, event_id=event_id)

        # Path guard: only a key this event was handed an upload URL for. Stops a caller
        # registering another tenant's / an arbitrary object path.
        if not storage_path.startswith(self._event_prefix(school_id, event_id)):
            raise ValidationError("storage_path is outside this event's prefix")

        return await self._media.create(
            school_id=school_id,
            event_id=event_id,
            storage_path=storage_path,
            media_type=media_type,
        )

    # ---- reads ----------------------------------------------------------

    async def get_media(self, *, school_id: str, media_id: str) -> Media:
        media = await self._media.get(school_id, media_id)
        if media is None:
            raise NotFoundError(f"media not found: {media_id}")
        return media

    async def list_event_media(self, *, school_id: str, event_id: str) -> list[Media]:
        # 404 for a missing/foreign event (rather than a bare empty list).
        await self._require_event(school_id=school_id, event_id=event_id)
        return await self._media.list_by_event(school_id, event_id)

    # ---- internals ------------------------------------------------------

    async def _require_event(self, *, school_id: str, event_id: str) -> Event:
        event = await self._events.get(school_id, event_id)
        if event is None:
            raise NotFoundError(f"event not found: {event_id}")
        return event

    async def _require_active_event(self, *, school_id: str, event_id: str) -> None:
        event = await self._require_event(school_id=school_id, event_id=event_id)
        if event.status is not EventStatus.ACTIVE:
            raise ValidationError("event is archived")
