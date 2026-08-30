"""WhatsApp send use-cases (W2) — send a student ALL or a selected subset of THEIR photos.

Pure orchestration over ports only (no HTTP, no PIL, no RBAC — authorization is at the route,
the tenant is the caller's token ``school_id``). Student-centric: staff send one student their
effective photos; there is no photo-fanout. The endpoint loops server-side, best-effort per
media, with ONE budget check up front (the BP27 bulk pattern).

REUSE, never re-derive: the student's EFFECTIVE media set is read via
``GalleryService.student_media`` — the SAME BP5 correction overlay (rejected excluded, added
included) the galleries use, so a ``rejected`` appearance is NEVER sent and a client can never
force a photo the student doesn't effectively appear in (any requested-but-not-effective media
is recorded ``skipped``). Consent + safety: send only to a student whose ``whatsapp_opt_in`` is
true AND ``mobile_number`` is non-null; PII-free logging (the send log stores ``student_id``/
``media_id``, NEVER the phone number — not in a row, an ``error`` string, or the response).
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from backend.domain.errors import NotFoundError, UpstreamError, ValidationError
from backend.domain.models import (
    Media,
    WhatsAppSendItemResult,
    WhatsAppSendSummary,
)
from backend.domain.ports import (
    ObjectStore,
    StudentRepository,
    Thumbnailer,
    WhatsAppSender,
    WhatsAppSendLogRepository,
)
from backend.services.gallery_service import GalleryService
from backend.services.whatsapp_config_service import WhatsAppConfigService
from backend.services.whatsapp_image import make_whatsapp_variant

_log = structlog.get_logger(__name__)


def _utc_month_start(now: datetime) -> datetime:
    """The first instant of ``now``'s UTC calendar month — the budget window boundary."""
    return datetime(now.year, now.month, 1, tzinfo=UTC)


class WhatsAppShareService:
    def __init__(
        self,
        config_service: WhatsAppConfigService,
        gallery_service: GalleryService,
        students: StudentRepository,
        object_store: ObjectStore,
        thumbnailer: Thumbnailer,
        sender: WhatsAppSender,
        send_log: WhatsAppSendLogRepository,
        *,
        default_sender_number: str,
        download_url_ttl_s: int,
        image_max_edge: int,
        image_quality: int,
        image_max_bytes: int,
        image_quality_floor: int,
        monthly_send_cap: int,
        variant_prefix: str,
    ) -> None:
        self._config = config_service
        self._gallery = gallery_service
        self._students = students
        self._object_store = object_store
        self._thumbnailer = thumbnailer
        self._sender = sender
        self._send_log = send_log
        self._default_sender = default_sender_number
        self._ttl = download_url_ttl_s
        self._max_edge = image_max_edge
        self._quality = image_quality
        self._max_bytes = image_max_bytes
        self._quality_floor = image_quality_floor
        self._cap = monthly_send_cap
        self._prefix = variant_prefix.strip("/")

    async def send_student_photos(
        self,
        *,
        school_id: str,
        student_id: str,
        media_ids: list[str] | None,
        actor_user_id: str,
        actor_role: str,
    ) -> WhatsAppSendSummary:
        """Send one student ALL (``media_ids=None``) or a SELECTED subset of THEIR effective
        photos over WhatsApp. Gates fail fast (before any spend); the send loop is best-effort
        per media (one media's failure never aborts the batch) under a single monthly budget."""
        # 1) Student must exist in this tenant — 404 BEFORE anything (no leak, no send).
        student = await self._students.get(school_id, student_id)
        if student is None:
            raise NotFoundError(f"student not found: {student_id}")

        # 2) The school must have WhatsApp enabled.
        config = await self._config.get_config(school_id=school_id)
        if not config.enabled:
            raise ValidationError("WhatsApp sending is not enabled for this school")

        # 3) An approved sender + template are required.
        sender = config.sender_number or self._default_sender
        if not sender:
            raise ValidationError("no sender number configured")
        template = config.template_name
        if not template:
            raise ValidationError("no approved template configured")

        # 4) Consent gate: opted in AND a number on file.
        if not student.whatsapp_opt_in:
            raise ValidationError("student has not opted in to WhatsApp")
        recipient = student.mobile_number
        if recipient is None:
            raise ValidationError("student has no mobile number")

        # 5) The student's EFFECTIVE media (BP5 overlay, reused — never re-derived). If specific
        #    ids were requested, intersect: a requested media the student does NOT effectively
        #    appear in is recorded ``skipped`` "not entitled" (a client can't force a rejected
        #    photo). ``None`` → the whole effective set.
        effective = await self._gallery.student_media(
            school_id=school_id, student_id=student_id
        )
        effective_by_id: dict[str, Media] = {m.id: m for m in effective}
        results: list[WhatsAppSendItemResult] = []
        if media_ids is None:
            targets = list(effective)
        else:
            targets = []
            seen: set[str] = set()
            for mid in media_ids:
                if mid in seen:
                    continue  # de-dupe a repeated id in the request
                seen.add(mid)
                media = effective_by_id.get(mid)
                if media is None:
                    results.append(
                        WhatsAppSendItemResult(
                            media_id=mid, status="skipped", reason="not entitled"
                        )
                    )
                    continue
                targets.append(media)

        # 6) Budget: one check up front. Count this school's ``sent`` rows since the UTC month
        #    start; ``remaining`` decrements only on a real send below.
        sent_this_month = await self._send_log.count_sent_since(
            school_id, since=_utc_month_start(datetime.now(UTC))
        )
        remaining = self._cap - sent_this_month

        # 7) Best-effort loop per media (BP27 pattern).
        for media in targets:
            result = await self._send_one(
                school_id=school_id,
                student_id=student_id,
                media=media,
                recipient=recipient,
                sender=sender,
                template=template,
                actor_user_id=actor_user_id,
                actor_role=actor_role,
                over_budget=remaining <= 0,
            )
            results.append(result)
            if result.status == "sent":
                remaining -= 1

        sent = sum(1 for r in results if r.status == "sent")
        failed = sum(1 for r in results if r.status == "failed")
        skipped = sum(1 for r in results if r.status == "skipped")
        return WhatsAppSendSummary(
            results=results, sent=sent, failed=failed, skipped=skipped
        )

    async def _send_one(
        self,
        *,
        school_id: str,
        student_id: str,
        media: Media,
        recipient: str,
        sender: str,
        template: str,
        actor_user_id: str,
        actor_role: str,
        over_budget: bool,
    ) -> WhatsAppSendItemResult:
        """Attempt one media; record exactly one send-log row + return its result. PII-free —
        the recipient number is never passed to the log or put in an error string."""
        if over_budget:
            await self._record(
                school_id=school_id,
                student_id=student_id,
                media_id=media.id,
                actor_user_id=actor_user_id,
                actor_role=actor_role,
                sender=sender,
                status="skipped",
                provider_message_id=None,
                error="budget",
            )
            return WhatsAppSendItemResult(
                media_id=media.id, status="skipped", reason="budget"
            )

        # Produce the ≤5 MB variant; None → un-shrinkable / non-image / store outage.
        variant = await make_whatsapp_variant(
            self._object_store,
            self._thumbnailer,
            media.storage_path,
            max_edge=self._max_edge,
            quality=self._quality,
            max_bytes=self._max_bytes,
            quality_floor=self._quality_floor,
        )
        if variant is None:
            await self._record(
                school_id=school_id,
                student_id=student_id,
                media_id=media.id,
                actor_user_id=actor_user_id,
                actor_role=actor_role,
                sender=sender,
                status="failed",
                provider_message_id=None,
                error="image_too_large_or_unavailable",
            )
            return WhatsAppSendItemResult(
                media_id=media.id,
                status="failed",
                reason="image_too_large_or_unavailable",
            )

        # Upload the variant to a deterministic per-media key (a re-send OVERWRITES it, never
        # accumulates) + mint a short-lived signed URL to pass as image_url. v1 limit: the
        # variant OBJECT itself is not reaped (only the signed URL is short-lived) — one small
        # private JPEG per distinct media ever sent; a cleanup job is a documented follow-up.
        key = f"{self._prefix}/{school_id}/{media.id}.jpg"
        try:
            await self._object_store.upload_bytes(
                key, variant, content_type="image/jpeg"
            )
            url = await self._object_store.create_signed_download_url(
                key, expires_in_s=self._ttl
            )
        except UpstreamError:
            await self._record(
                school_id=school_id,
                student_id=student_id,
                media_id=media.id,
                actor_user_id=actor_user_id,
                actor_role=actor_role,
                sender=sender,
                status="failed",
                provider_message_id=None,
                error="upload_failed",
            )
            return WhatsAppSendItemResult(
                media_id=media.id, status="failed", reason="upload_failed"
            )

        # Send. A transport (UpstreamError) or rejected-recipient/template (ValidationError)
        # failure is isolated to this media — record failed, keep the batch going. The error
        # string is a short PII-free reason, NEVER str(exc) (which could carry the number).
        try:
            receipt = await self._sender.send_image(
                to=recipient,
                image_url=url,
                template_name=template,
                sender_number=sender,
                caption=None,
            )
        except (UpstreamError, ValidationError):
            await self._record(
                school_id=school_id,
                student_id=student_id,
                media_id=media.id,
                actor_user_id=actor_user_id,
                actor_role=actor_role,
                sender=sender,
                status="failed",
                provider_message_id=None,
                error="send_failed",
            )
            return WhatsAppSendItemResult(
                media_id=media.id, status="failed", reason="send_failed"
            )

        await self._record(
            school_id=school_id,
            student_id=student_id,
            media_id=media.id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            sender=sender,
            status="sent",
            provider_message_id=receipt.provider_message_id,
            error=None,
        )
        return WhatsAppSendItemResult(media_id=media.id, status="sent")

    async def _record(
        self,
        *,
        school_id: str,
        student_id: str,
        media_id: str,
        actor_user_id: str,
        actor_role: str,
        sender: str,
        status: str,
        provider_message_id: str | None,
        error: str | None,
    ) -> None:
        """Record one send-log row best-effort — a failed audit must NEVER abort the batch. The
        recipient phone number is deliberately not passed (PII-free); logging is ids only."""
        try:
            await self._send_log.record(
                school_id=school_id,
                student_id=student_id,
                media_id=media_id,
                actor_user_id=actor_user_id,
                actor_role=actor_role,
                sender_number=sender,
                status=status,
                provider_message_id=provider_message_id,
                error=error,
            )
        except Exception:  # noqa: BLE001 — best-effort audit; never fail the send batch
            _log.warning(
                "whatsapp_send_log_record_failed",
                school_id=school_id,
                student_id=student_id,
                media_id=media_id,
                status=status,
                exc_info=True,
            )
