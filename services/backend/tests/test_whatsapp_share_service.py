"""WhatsAppShareService (W2) — the gate truth table + the best-effort send loop, on fakes.

Covers: config-disabled / not-opted-in / no-number / no-template / no-sender → 400 + NO send;
the EFFECTIVE-appearance overlay is REUSED (a REJECTED appearance is never sent; an ADDED one
IS); the happy path (N sent, N log rows, `to` == the mobile number, resolved sender/template/
signed url); partial-failure isolation (one media raises → failed, the rest sent); the monthly
budget cap stops sends; the ≤5 MB skip (an un-shrinkable variant → failed, not sent); and PII —
no log row / error string carries the phone number.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from backend.domain.errors import UpstreamError, ValidationError
from backend.domain.models import (
    Appearance,
    MatchCorrection,
    MatchVerdict,
    Media,
    PlatformConfig,
    SchoolWhatsAppConfig,
    Student,
    WhatsAppReceipt,
    WhatsAppSendSummary,
)
from backend.domain.ports import Thumbnailer
from backend.services.gallery_service import GalleryService
from backend.services.platform_config_service import PlatformConfigService
from backend.services.whatsapp_config_service import WhatsAppConfigService
from backend.services.whatsapp_share_service import (
    WhatsAppShareService,
    _utc_month_start,
)
from backend.services.whatsapp_share_service import WhatsAppShareService as _Svc
from backend_fakes import (
    FakeDownloadAuditRepo,
    FakeEventRepo,
    FakeMatchCorrectionRepo,
    FakeMediaRepo,
    FakeMlResultsReader,
    FakeObjectStore,
    FakePlatformConfigRepo,
    FakeStudentRepo,
    FakeThumbnailer,
    FakeWhatsAppConfigRepo,
    FakeWhatsAppSendLogRepo,
    make_appearance,
    make_event,
    make_match_correction,
    make_media,
    make_student,
)

_MOBILE = "15559990000"
_SENDER = "15551234567"
_TEMPLATE = "photo_notice"


class _SizedThumbnailer:
    """Thumbnailer double whose output size + success depend on the per-call override — so the
    W2 ≤5 MB step-down + the un-shrinkable path are exercised. ``size_for`` maps a quality to a
    byte length; ``produces`` False → always None (non-image)."""

    def __init__(
        self,
        *,
        size_for: Callable[[int | None, int | None], int] = lambda q, edge: 10,
        produces: bool = True,
    ) -> None:
        self._size_for = size_for
        self._produces = produces
        self.calls: list[tuple[int | None, int | None]] = []

    async def make_thumbnail(
        self, data: bytes, *, max_edge: int | None = None, quality: int | None = None
    ) -> bytes | None:
        self.calls.append((max_edge, quality))
        if not self._produces:
            return None
        return b"x" * self._size_for(quality, max_edge)


def _config(
    *,
    enabled: bool,
    sender: str | None = _SENDER,
    template: str | None = _TEMPLATE,
) -> SchoolWhatsAppConfig:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return SchoolWhatsAppConfig(
        school_id="school-1",
        enabled=enabled,
        sender_number=sender,
        template_name=template,
        business_name="Alpha",
        created_at=now,
        updated_at=now,
    )


@dataclass
class _Handles:
    students: FakeStudentRepo
    sender: _RecordingSender
    log: FakeWhatsAppSendLogRepo
    store: FakeObjectStore


def _build(
    *,
    student: Student | None = None,
    appearances: list[Appearance] | None = None,
    corrections: list[MatchCorrection] | None = None,
    media: list[Media] | None = None,
    config: SchoolWhatsAppConfig | None = None,
    sender: _RecordingSender | None = None,
    thumbnailer: Thumbnailer | None = None,
    object_store: FakeObjectStore | None = None,
    send_log: FakeWhatsAppSendLogRepo | None = None,
    default_sender: str = "",
    monthly_cap: int = 12000,
    platform_config: PlatformConfig | None = None,
) -> tuple[_Svc, _Handles]:
    """Wire a WhatsAppShareService over fakes. Returns (service, handles). ``platform_config``
    (W-live-test) drives the interim path; default None → interim off → template path."""
    student = student or make_student(
        id="stu-1",
        school_id="school-1",
        mobile_number=_MOBILE,
        whatsapp_opt_in=True,
    )
    students = FakeStudentRepo([student])
    reader = FakeMlResultsReader(appearances or [])
    corrections_repo = FakeMatchCorrectionRepo(corrections or [])
    media_repo = FakeMediaRepo(media or [])
    events = FakeEventRepo([make_event(id="event-1", school_id="school-1")])
    store = object_store or FakeObjectStore()
    audit = FakeDownloadAuditRepo()
    gallery = GalleryService(
        reader,
        students,
        events,
        media_repo,
        corrections_repo,
        store,
        audit,
        download_url_ttl_s=3600,
    )
    config_repo = FakeWhatsAppConfigRepo(
        [config] if config is not None else [_config(enabled=True)]
    )
    config_service = WhatsAppConfigService(
        config_repo, default_sender_number=default_sender, provider="gupshup"
    )
    platform_service = PlatformConfigService(
        FakePlatformConfigRepo(platform_config)
    )
    fake_sender = sender or _RecordingSender()
    log = send_log or FakeWhatsAppSendLogRepo()
    service = WhatsAppShareService(
        config_service,
        platform_service,
        gallery,
        students,
        store,
        thumbnailer or FakeThumbnailer(),
        fake_sender,
        log,
        default_sender_number=default_sender,
        download_url_ttl_s=3600,
        image_max_edge=2000,
        image_quality=80,
        image_max_bytes=4_800_000,
        image_quality_floor=40,
        monthly_send_cap=monthly_cap,
        variant_prefix="whatsapp-variants",
    )
    return service, _Handles(students=students, sender=fake_sender, log=log, store=store)


class _RecordingSender:
    """A WhatsAppSender that records each call + can raise on a chosen media (by image_url
    substring) to exercise per-media failure isolation. W-live-test: also records the free-form
    ``send_text``/``send_image_link`` used by the interim path."""

    def __init__(self, *, raise_on_url_substr: str | None = None) -> None:
        self.sent: list[dict[str, str | None]] = []
        self.texts: list[dict[str, str]] = []
        self.image_links: list[dict[str, str | None]] = []
        self._raise_on = raise_on_url_substr

    async def send_image(
        self,
        *,
        to: str,
        image_url: str,
        template_name: str,
        sender_number: str,
        caption: str | None = None,
    ) -> WhatsAppReceipt:
        if self._raise_on is not None and self._raise_on in image_url:
            raise UpstreamError("transport blip")  # no phone number in the message
        self.sent.append(
            {
                "to": to,
                "image_url": image_url,
                "template": template_name,
                "sender": sender_number,
            }
        )
        return WhatsAppReceipt(provider_message_id=f"pm-{len(self.sent)}", to=to)

    async def send_text(
        self, *, to: str, body: str, sender_number: str
    ) -> WhatsAppReceipt:
        self.texts.append({"to": to, "body": body, "sender": sender_number})
        return WhatsAppReceipt(provider_message_id=f"txt-{len(self.texts)}", to=to)

    async def send_image_link(
        self,
        *,
        to: str,
        image_url: str,
        caption: str | None,
        sender_number: str,
    ) -> WhatsAppReceipt:
        if self._raise_on is not None and self._raise_on in image_url:
            raise UpstreamError("transport blip")
        self.image_links.append(
            {"to": to, "image_url": image_url, "caption": caption, "sender": sender_number}
        )
        return WhatsAppReceipt(
            provider_message_id=f"link-{len(self.image_links)}", to=to
        )


async def _send(
    service: _Svc, *, media_ids: list[str] | None = None
) -> WhatsAppSendSummary:
    return await service.send_student_photos(
        school_id="school-1",
        student_id="stu-1",
        media_ids=media_ids,
        actor_user_id="actor-1",
        actor_role="school_admin",
    )


# ---- gate truth table ---------------------------------------------------


async def test_config_disabled_is_400_and_no_send() -> None:
    service, h = _build(config=_config(enabled=False))
    with pytest.raises(ValidationError):
        await _send(service)
    assert h.sender.sent == []
    assert h.log.rows == []


async def test_not_opted_in_is_400_and_no_send() -> None:
    student = make_student(
        id="stu-1", school_id="school-1", mobile_number=_MOBILE, whatsapp_opt_in=False
    )
    service, h = _build(student=student)
    with pytest.raises(ValidationError):
        await _send(service)
    assert h.sender.sent == []


async def test_no_number_is_400_and_no_send() -> None:
    student = make_student(
        id="stu-1", school_id="school-1", mobile_number=None, whatsapp_opt_in=True
    )
    service, h = _build(student=student)
    with pytest.raises(ValidationError):
        await _send(service)
    assert h.sender.sent == []


async def test_no_template_is_400() -> None:
    service, h = _build(config=_config(enabled=True, template=None))
    with pytest.raises(ValidationError):
        await _send(service)
    assert h.sender.sent == []


async def test_no_sender_is_400() -> None:
    # Config sender None AND no platform default → no sender number configured.
    service, h = _build(config=_config(enabled=True, sender=None), default_sender="")
    with pytest.raises(ValidationError):
        await _send(service)
    assert h.sender.sent == []


# ---- effective-appearance overlay (REUSED, not re-derived) --------------


async def test_rejected_appearance_is_not_sent() -> None:
    """A REJECTED (media, student) pair must never be sent — the BP5 overlay in the reused
    GalleryService.student_media drops it, so the media isn't even a target."""
    media = [make_media(id="m1", school_id="school-1", event_id="event-1")]
    appearances = [
        make_appearance(student_id="stu-1", media_id="m1", event_id="event-1")
    ]
    corrections = [
        make_match_correction(
            media_id="m1",
            student_id="stu-1",
            event_id="event-1",
            verdict=MatchVerdict.REJECTED,
        )
    ]
    service, h = _build(
        appearances=appearances, corrections=corrections, media=media
    )
    summary = await _send(service)  # media_ids=None → all effective
    assert summary.sent == 0
    assert h.sender.sent == []  # provably not sent


async def test_rejected_appearance_requested_by_id_is_skipped_not_sent() -> None:
    """Even if the client explicitly names a rejected media id, it's skipped 'not entitled'."""
    media = [make_media(id="m1", school_id="school-1", event_id="event-1")]
    appearances = [
        make_appearance(student_id="stu-1", media_id="m1", event_id="event-1")
    ]
    corrections = [
        make_match_correction(
            media_id="m1",
            student_id="stu-1",
            event_id="event-1",
            verdict=MatchVerdict.REJECTED,
        )
    ]
    service, h = _build(
        appearances=appearances, corrections=corrections, media=media
    )
    summary = await _send(service, media_ids=["m1"])
    assert summary.sent == 0
    assert summary.skipped == 1
    assert summary.results[0].reason == "not entitled"
    assert h.sender.sent == []


async def test_added_correction_media_is_sent() -> None:
    """An ADDED (report-a-miss) pair with no ML match IS in the effective set → sent."""
    media = [make_media(id="m2", school_id="school-1", event_id="event-1")]
    corrections = [
        make_match_correction(
            media_id="m2",
            student_id="stu-1",
            event_id="event-1",
            verdict=MatchVerdict.ADDED,
        )
    ]
    service, h = _build(appearances=[], corrections=corrections, media=media)
    summary = await _send(service)
    assert summary.sent == 1
    assert [s["to"] for s in h.sender.sent] == [_MOBILE]


# ---- happy path ---------------------------------------------------------


async def test_happy_path_sends_all_effective() -> None:
    media = [
        make_media(id="m1", school_id="school-1", event_id="event-1"),
        make_media(id="m2", school_id="school-1", event_id="event-1"),
    ]
    appearances = [
        make_appearance(student_id="stu-1", media_id="m1", event_id="event-1"),
        make_appearance(student_id="stu-1", media_id="m2", event_id="event-1"),
    ]
    service, h = _build(appearances=appearances, media=media)
    summary = await _send(service)
    assert summary.sent == 2 and summary.failed == 0 and summary.skipped == 0
    # Every send carried the resolved sender/template + the recipient's real mobile number.
    for s in h.sender.sent:
        assert s["to"] == _MOBILE
        assert s["sender"] == _SENDER
        assert s["template"] == _TEMPLATE
        assert "whatsapp-variants" in str(s["image_url"])  # the signed variant url
    # N `sent` log rows, `to` never stored (student_id/media_id are).
    rows = h.log.rows
    assert len(rows) == 2 and all(r.status == "sent" for r in rows)
    assert {r.media_id for r in rows} == {"m1", "m2"}
    assert all(r.provider_message_id for r in rows)


async def test_selected_subset_only_sends_those() -> None:
    media = [
        make_media(id="m1", school_id="school-1", event_id="event-1"),
        make_media(id="m2", school_id="school-1", event_id="event-1"),
    ]
    appearances = [
        make_appearance(student_id="stu-1", media_id="m1", event_id="event-1"),
        make_appearance(student_id="stu-1", media_id="m2", event_id="event-1"),
    ]
    service, h = _build(appearances=appearances, media=media)
    summary = await _send(service, media_ids=["m1"])
    assert summary.sent == 1
    assert [s["image_url"] and "m1.jpg" in str(s["image_url"]) for s in h.sender.sent] == [True]


# ---- partial-failure isolation ------------------------------------------


async def test_one_media_failure_does_not_abort_the_batch() -> None:
    media = [
        make_media(id="m1", school_id="school-1", event_id="event-1"),
        make_media(id="m2", school_id="school-1", event_id="event-1"),
    ]
    appearances = [
        make_appearance(student_id="stu-1", media_id="m1", event_id="event-1"),
        make_appearance(student_id="stu-1", media_id="m2", event_id="event-1"),
    ]
    sender = _RecordingSender(raise_on_url_substr="m1.jpg")  # m1 send raises
    service, h = _build(appearances=appearances, media=media, sender=sender)
    summary = await _send(service)
    assert summary.sent == 1 and summary.failed == 1
    by_media = {r.media_id: r.status for r in summary.results}
    assert by_media == {"m1": "failed", "m2": "sent"}
    # The batch wasn't aborted: m2 still sent. A `failed` log row exists for m1 with a PII-free
    # reason (never the phone number).
    failed_rows = [r for r in h.log.rows if r.status == "failed"]
    assert len(failed_rows) == 1
    assert failed_rows[0].error is not None and _MOBILE not in failed_rows[0].error


# ---- budget cap ---------------------------------------------------------


async def test_budget_cap_stops_sends() -> None:
    media = [
        make_media(id="m1", school_id="school-1", event_id="event-1"),
        make_media(id="m2", school_id="school-1", event_id="event-1"),
    ]
    appearances = [
        make_appearance(student_id="stu-1", media_id="m1", event_id="event-1"),
        make_appearance(student_id="stu-1", media_id="m2", event_id="event-1"),
    ]
    # Seed the log so 1 send remains this month (cap=2, already 1 sent).
    log = FakeWhatsAppSendLogRepo()
    await log.record(
        school_id="school-1",
        student_id="stu-1",
        media_id="m0",
        actor_user_id="a",
        actor_role="school_admin",
        sender_number=_SENDER,
        status="sent",
        provider_message_id="pm-0",
        error=None,
    )
    service, h = _build(
        appearances=appearances, media=media, send_log=log, monthly_cap=2
    )
    summary = await _send(service)
    assert summary.sent == 1 and summary.skipped == 1
    over = [r for r in summary.results if r.status == "skipped"]
    assert over and over[0].reason == "budget"
    # Only one NEW send hit the provider (nothing past the budget).
    assert len(h.sender.sent) == 1


async def test_budget_zero_remaining_sends_nothing() -> None:
    media = [make_media(id="m1", school_id="school-1", event_id="event-1")]
    appearances = [
        make_appearance(student_id="stu-1", media_id="m1", event_id="event-1")
    ]
    log = FakeWhatsAppSendLogRepo()
    await log.record(
        school_id="school-1",
        student_id="stu-1",
        media_id="m0",
        actor_user_id="a",
        actor_role="school_admin",
        sender_number=_SENDER,
        status="sent",
        provider_message_id="pm-0",
        error=None,
    )
    service, h = _build(
        appearances=appearances, media=media, send_log=log, monthly_cap=1
    )
    summary = await _send(service)
    assert summary.sent == 0 and summary.skipped == 1
    assert h.sender.sent == []


# ---- ≤5 MB skip ---------------------------------------------------------


async def test_unshrinkable_image_is_failed_not_sent() -> None:
    media = [make_media(id="m1", school_id="school-1", event_id="event-1")]
    appearances = [
        make_appearance(student_id="stu-1", media_id="m1", event_id="event-1")
    ]
    # Every re-encode is far over the 4.8 MB cap → make_whatsapp_variant returns None.
    huge = _SizedThumbnailer(size_for=lambda q, edge: 10_000_000)
    service, h = _build(appearances=appearances, media=media, thumbnailer=huge)
    summary = await _send(service)
    assert summary.sent == 0 and summary.failed == 1
    assert summary.results[0].reason == "image_too_large_or_unavailable"
    assert h.sender.sent == []


async def test_non_image_variant_none_is_failed_not_sent() -> None:
    media = [make_media(id="m1", school_id="school-1", event_id="event-1")]
    appearances = [
        make_appearance(student_id="stu-1", media_id="m1", event_id="event-1")
    ]
    non_image = _SizedThumbnailer(produces=False)  # decode failure → None
    service, h = _build(appearances=appearances, media=media, thumbnailer=non_image)
    summary = await _send(service)
    assert summary.failed == 1 and h.sender.sent == []


# ---- tenant + PII -------------------------------------------------------


async def test_foreign_student_is_404_before_any_send() -> None:
    from backend.domain.errors import NotFoundError

    service, h = _build()
    with pytest.raises(NotFoundError):
        await service.send_student_photos(
            school_id="OTHER-SCHOOL",
            student_id="stu-1",
            media_ids=None,
            actor_user_id="a",
            actor_role="school_admin",
        )
    assert h.sender.sent == []


async def test_no_log_row_or_error_contains_the_phone_number() -> None:
    media = [
        make_media(id="m1", school_id="school-1", event_id="event-1"),
        make_media(id="m2", school_id="school-1", event_id="event-1"),
    ]
    appearances = [
        make_appearance(student_id="stu-1", media_id="m1", event_id="event-1"),
        make_appearance(student_id="stu-1", media_id="m2", event_id="event-1"),
    ]
    sender = _RecordingSender(raise_on_url_substr="m1.jpg")  # a failure + a success
    service, h = _build(appearances=appearances, media=media, sender=sender)
    await _send(service)
    for r in h.log.rows:
        # The number appears in NO field of any log row (sender_number is the platform sender,
        # not the recipient; error/provider_message_id/status never carry it).
        assert _MOBILE not in (r.error or "")
        assert _MOBILE not in (r.provider_message_id or "")
        assert _MOBILE != r.sender_number  # sender_number is the SENDER, not the recipient


def test_utc_month_start_is_first_of_month() -> None:
    now = datetime(2026, 8, 30, 17, 45, tzinfo=UTC)
    assert _utc_month_start(now) == datetime(2026, 8, 1, tzinfo=UTC)


# ---- interim free-form send (W-live-test) -------------------------------

_TEST_NUMBER = "919999888877"


def _platform(*, interim_mode: bool, number: str | None = _TEST_NUMBER) -> PlatformConfig:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return PlatformConfig(
        id="platform",
        meta_access_token=None,
        interim_test_number=number,
        interim_mode=interim_mode,
        created_at=now,
        updated_at=now,
    )


async def test_interim_mode_sends_text_intro_plus_photos_to_test_number() -> None:
    """Interim mode: a text intro + N image_link sends, all to the hardcoded test number, with
    the consent gate SKIPPED (student not opted in). Send-log rows recorded per photo."""
    media = [
        make_media(id="m1", school_id="school-1", event_id="event-1"),
        make_media(id="m2", school_id="school-1", event_id="event-1"),
    ]
    appearances = [
        make_appearance(student_id="stu-1", media_id="m1", event_id="event-1"),
        make_appearance(student_id="stu-1", media_id="m2", event_id="event-1"),
    ]
    # A student NOT opted in + no number — proves the interim path skips the consent gate.
    student = make_student(
        id="stu-1", school_id="school-1", mobile_number=None, whatsapp_opt_in=False
    )
    sender = _RecordingSender()
    service, h = _build(
        student=student,
        appearances=appearances,
        media=media,
        sender=sender,
        platform_config=_platform(interim_mode=True),
    )
    summary = await _send(service)
    assert summary.sent == 2 and summary.failed == 0 and summary.skipped == 0
    # Exactly one intro text to the test number, naming the count.
    assert len(sender.texts) == 1
    assert sender.texts[0]["to"] == _TEST_NUMBER
    assert "2" in sender.texts[0]["body"]
    # Each photo went to the test number via the free-form image_link (NOT the template send).
    assert len(sender.image_links) == 2
    assert all(link["to"] == _TEST_NUMBER for link in sender.image_links)
    assert sender.sent == []  # template send_image never used
    # Send-log rows recorded (student_id/media_id, never a recipient PII field).
    rows = h.log.rows
    assert len(rows) == 2 and all(r.status == "sent" for r in rows)
    assert {r.media_id for r in rows} == {"m1", "m2"}
    # The SENT path records the platform sender ("interim" here, default unset), NEVER the
    # recipient test number (the "not-PII" invariant on sender_number — B1 regression guard).
    assert all(r.sender_number == "interim" for r in rows)
    assert all(_TEST_NUMBER != r.sender_number for r in rows)


async def test_interim_mode_reuses_effective_overlay_rejected_not_sent() -> None:
    """Even in interim mode a REJECTED appearance is never sent (the BP5 overlay is reused)."""
    media = [make_media(id="m1", school_id="school-1", event_id="event-1")]
    appearances = [
        make_appearance(student_id="stu-1", media_id="m1", event_id="event-1")
    ]
    corrections = [
        make_match_correction(
            media_id="m1",
            student_id="stu-1",
            event_id="event-1",
            verdict=MatchVerdict.REJECTED,
        )
    ]
    sender = _RecordingSender()
    service, h = _build(
        appearances=appearances,
        corrections=corrections,
        media=media,
        sender=sender,
        platform_config=_platform(interim_mode=True),
    )
    summary = await _send(service)
    assert summary.sent == 0
    assert sender.image_links == []  # provably not sent


async def test_interim_mode_respects_budget_cap() -> None:
    media = [
        make_media(id="m1", school_id="school-1", event_id="event-1"),
        make_media(id="m2", school_id="school-1", event_id="event-1"),
    ]
    appearances = [
        make_appearance(student_id="stu-1", media_id="m1", event_id="event-1"),
        make_appearance(student_id="stu-1", media_id="m2", event_id="event-1"),
    ]
    log = FakeWhatsAppSendLogRepo()
    await log.record(
        school_id="school-1", student_id="stu-1", media_id="m0", actor_user_id="a",
        actor_role="school_admin", sender_number=_TEST_NUMBER, status="sent",
        provider_message_id="pm-0", error=None,
    )
    sender = _RecordingSender()
    service, h = _build(
        appearances=appearances, media=media, sender=sender, send_log=log,
        monthly_cap=2, platform_config=_platform(interim_mode=True),
    )
    summary = await _send(service)
    assert summary.sent == 1 and summary.skipped == 1
    assert len(sender.image_links) == 1  # only one NEW photo hit the provider


async def test_interim_intro_failure_does_not_abort_photos() -> None:
    """A failing intro text (window/auth) must NOT stop the photos from being sent."""

    class _IntroFailsSender(_RecordingSender):
        async def send_text(
            self, *, to: str, body: str, sender_number: str
        ) -> WhatsAppReceipt:
            raise UpstreamError("outside 24h window")  # no PII

    media = [make_media(id="m1", school_id="school-1", event_id="event-1")]
    appearances = [
        make_appearance(student_id="stu-1", media_id="m1", event_id="event-1")
    ]
    sender = _IntroFailsSender()
    service, h = _build(
        appearances=appearances, media=media, sender=sender,
        platform_config=_platform(interim_mode=True),
    )
    summary = await _send(service)
    assert summary.sent == 1  # the photo still went out
    assert len(sender.image_links) == 1


async def test_interim_mode_off_uses_template_path_regression() -> None:
    """With interim mode OFF (default) the existing template path runs unchanged: the consent
    gate applies (opted-in + number) and send_image (template) is used, not the free-form calls."""
    media = [make_media(id="m1", school_id="school-1", event_id="event-1")]
    appearances = [
        make_appearance(student_id="stu-1", media_id="m1", event_id="event-1")
    ]
    sender = _RecordingSender()
    service, h = _build(
        appearances=appearances,
        media=media,
        sender=sender,
        platform_config=_platform(interim_mode=False),
    )
    summary = await _send(service)
    assert summary.sent == 1
    # The TEMPLATE send was used; the free-form interim calls were not.
    assert len(sender.sent) == 1 and sender.sent[0]["template"] == _TEMPLATE
    assert sender.texts == [] and sender.image_links == []


async def test_interim_mode_without_number_falls_back_to_template() -> None:
    """interim_mode True but NO test number → not interim; the template path runs (consent
    applies)."""
    media = [make_media(id="m1", school_id="school-1", event_id="event-1")]
    appearances = [
        make_appearance(student_id="stu-1", media_id="m1", event_id="event-1")
    ]
    sender = _RecordingSender()
    service, h = _build(
        appearances=appearances,
        media=media,
        sender=sender,
        platform_config=_platform(interim_mode=True, number=None),
    )
    summary = await _send(service)
    assert summary.sent == 1
    assert len(sender.sent) == 1  # template path
    assert sender.image_links == []


async def test_no_recipient_number_leaks_in_interim_log_rows() -> None:
    """PII: no interim send-log row carries the test recipient number in error/provider id."""
    media = [make_media(id="m1", school_id="school-1", event_id="event-1")]
    appearances = [
        make_appearance(student_id="stu-1", media_id="m1", event_id="event-1")
    ]
    sender = _RecordingSender(raise_on_url_substr="m1.jpg")  # force a failure
    service, h = _build(
        appearances=appearances, media=media, sender=sender,
        platform_config=_platform(interim_mode=True),
    )
    await _send(service)
    for r in h.log.rows:
        assert _TEST_NUMBER not in (r.error or "")
        assert _TEST_NUMBER not in (r.provider_message_id or "")
        # The recipient (test) number is NEVER the log's sender_number (that column is not-PII);
        # with no platform default sender configured it's the literal "interim" marker.
        assert _TEST_NUMBER != r.sender_number
        assert r.sender_number == "interim"
