"""Event-photo fan-out — select photos in an event, send each appearing student their subset.

Covers the security spine (the recipient set is the BP5 EFFECTIVE overlay ∩ the selected media —
a rejected pair excluded, an added one included, a crafted/foreign media id contributing nothing)
+ the fan-out send (reuses the fully-gated per-student send: a non-consenting student is SKIPPED
not aborting the batch; the budget is respected across students; interim diverts all to the test
number; PII-free) + the two routes (preview + send: permissions, tenant, the over-cap 422).
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.domain.errors import NotFoundError, ValidationError
from backend.domain.models import (
    Appearance,
    EventPhotoSendSummary,
    MatchCorrection,
    MatchVerdict,
    Media,
    PlatformConfig,
    Role,
    Student,
    User,
    WhatsAppReceipt,
)
from backend.main import create_app
from backend.services.gallery_service import GalleryService
from backend.services.platform_config_service import PlatformConfigService
from backend.services.whatsapp_share_service import WhatsAppShareService
from backend_fakes import (
    FakeDownloadAuditRepo,
    FakeEventRepo,
    FakeMatchCorrectionRepo,
    FakeMediaRepo,
    FakeMlResultsReader,
    FakeObjectStore,
    FakePlatformConfigRepo,
    FakeSchoolRepo,
    FakeStudentRepo,
    FakeThumbnailer,
    FakeUserRepo,
    FakeWhatsAppSendLogRepo,
    SeededContainer,
    make_appearance,
    make_event,
    make_match_correction,
    make_media,
    make_school,
    make_student,
    make_user,
)
from fastapi.testclient import TestClient

_SENDER = "15551234567"
_TEMPLATE = "photo_notice"
_TEST_NUMBER = "919999888877"


def _platform_config(
    *,
    sender: str | None = _SENDER,
    template: str | None = _TEMPLATE,
    interim_test_number: str | None = None,
) -> PlatformConfig:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return PlatformConfig(
        id="platform",
        meta_access_token=None,
        sender_number=sender,
        template_name=template,
        interim_test_number=interim_test_number,
        interim_mode=False,
        created_at=now,
        updated_at=now,
    )


class _RecordingSender:
    """Records each template send (+ the free-form interim calls). No recipient PII leaks by design
    of the share service; we assert that separately."""

    def __init__(self) -> None:
        self.sent: list[dict[str, str | None]] = []
        self.texts: list[dict[str, str]] = []
        self.image_links: list[dict[str, str | None]] = []

    async def send_image(
        self,
        *,
        to: str,
        image_url: str,
        template_name: str,
        sender_number: str,
        caption: str | None = None,
    ) -> WhatsAppReceipt:
        self.sent.append({"to": to, "image_url": image_url, "sender": sender_number})
        return WhatsAppReceipt(provider_message_id=f"pm-{len(self.sent)}", to=to)

    async def send_text(
        self, *, to: str, body: str, sender_number: str
    ) -> WhatsAppReceipt:
        self.texts.append({"to": to, "body": body})
        return WhatsAppReceipt(provider_message_id=f"txt-{len(self.texts)}", to=to)

    async def send_image_link(
        self, *, to: str, image_url: str, caption: str | None, sender_number: str
    ) -> WhatsAppReceipt:
        self.image_links.append({"to": to, "image_url": image_url})
        return WhatsAppReceipt(
            provider_message_id=f"link-{len(self.image_links)}", to=to
        )


def _gallery(
    *,
    students: list[Student],
    appearances: list[Appearance],
    corrections: list[MatchCorrection] | None = None,
    media: list[Media],
    store: FakeObjectStore | None = None,
) -> GalleryService:
    return GalleryService(
        FakeMlResultsReader(appearances),
        FakeStudentRepo(students),
        FakeEventRepo([make_event(id="event-1", school_id="school-1")]),
        FakeMediaRepo(media),
        FakeMatchCorrectionRepo(corrections or []),
        store or FakeObjectStore(),
        FakeDownloadAuditRepo(),
        download_url_ttl_s=3600,
    )


def _share(
    *,
    gallery: GalleryService,
    students: list[Student],
    platform_config: PlatformConfig | None = None,
    sender: _RecordingSender | None = None,
    send_log: FakeWhatsAppSendLogRepo | None = None,
    default_sender: str = "",
    monthly_cap: int = 12000,
    store: FakeObjectStore | None = None,
) -> tuple[WhatsAppShareService, _RecordingSender, FakeWhatsAppSendLogRepo]:
    fake_sender = sender or _RecordingSender()
    log = send_log or FakeWhatsAppSendLogRepo()
    platform_service = PlatformConfigService(
        FakePlatformConfigRepo(
            platform_config if platform_config is not None else _platform_config()
        )
    )
    service = WhatsAppShareService(
        platform_service,
        gallery,
        FakeStudentRepo(students),
        store or FakeObjectStore(),
        FakeThumbnailer(),
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
    return service, fake_sender, log


def _student(id: str, *, opted_in: bool = True, number: str | None = "15551110000") -> Student:
    student: Student = make_student(
        id=id, school_id="school-1", mobile_number=number, whatsapp_opt_in=opted_in
    )
    return student


def _media(*ids: str) -> list[Media]:
    return [make_media(id=i, school_id="school-1", event_id="event-1") for i in ids]


async def _recipients(
    gallery: GalleryService, media_ids: list[str]
) -> list[tuple[Student, list[str]]]:
    return await gallery.event_photo_recipients(
        school_id="school-1", event_id="event-1", media_ids=media_ids
    )


# ---- GalleryService.event_photo_recipients (the recipient set) -----------


async def test_recipients_groups_effective_by_student() -> None:
    # a & b each appear in a subset of the selection; a non-selected media (m3) is ignored.
    students = [_student("a"), _student("b")]
    media = _media("m1", "m2", "m3")
    appearances = [
        make_appearance(student_id="a", media_id="m1", event_id="event-1"),
        make_appearance(student_id="a", media_id="m2", event_id="event-1"),
        make_appearance(student_id="b", media_id="m2", event_id="event-1"),
        make_appearance(student_id="b", media_id="m3", event_id="event-1"),  # not selected
    ]
    gallery = _gallery(students=students, appearances=appearances, media=media)
    got = await _recipients(gallery, ["m1", "m2"])
    by_id = {s.id: set(ids) for s, ids in got}
    assert by_id == {"a": {"m1", "m2"}, "b": {"m2"}}
    # Ordered most-matched-first (a has 2, b has 1).
    assert [s.id for s, _ in got] == ["a", "b"]


async def test_recipients_excludes_rejected_includes_added() -> None:
    students = [_student("a")]
    media = _media("m1", "m2")
    appearances = [
        make_appearance(student_id="a", media_id="m1", event_id="event-1"),
    ]
    corrections = [
        # a rejected on m1 (removed), an added on m2 (included even w/o an ML match).
        make_match_correction(
            media_id="m1", student_id="a", event_id="event-1",
            verdict=MatchVerdict.REJECTED,
        ),
        make_match_correction(
            media_id="m2", student_id="a", event_id="event-1",
            verdict=MatchVerdict.ADDED,
        ),
    ]
    gallery = _gallery(
        students=students, appearances=appearances, corrections=corrections, media=media
    )
    got = await _recipients(gallery, ["m1", "m2"])
    assert {s.id: set(ids) for s, ids in got} == {"a": {"m2"}}  # m1 rejected out, m2 added in


async def test_recipients_ignores_foreign_media_id() -> None:
    # A media id not in the event's appearances contributes nothing (a crafted id can't leak).
    students = [_student("a")]
    appearances = [make_appearance(student_id="a", media_id="m1", event_id="event-1")]
    gallery = _gallery(students=students, appearances=appearances, media=_media("m1"))
    got = await _recipients(gallery, ["m1", "FOREIGN"])
    assert {s.id: set(ids) for s, ids in got} == {"a": {"m1"}}


async def test_recipients_whole_event_includes_all_matched_photos() -> None:
    # media_ids=None → the WHOLE event ("Announce on WhatsApp"): every effective pair, no filter.
    students = [_student("a"), _student("b")]
    media = _media("m1", "m2", "m3")
    appearances = [
        make_appearance(student_id="a", media_id="m1", event_id="event-1"),
        make_appearance(student_id="a", media_id="m2", event_id="event-1"),
        make_appearance(student_id="b", media_id="m3", event_id="event-1"),
    ]
    gallery = _gallery(students=students, appearances=appearances, media=media)
    got = await gallery.event_photo_recipients(
        school_id="school-1", event_id="event-1", media_ids=None
    )
    assert {s.id: set(ids) for s, ids in got} == {"a": {"m1", "m2"}, "b": {"m3"}}


async def test_recipients_whole_event_still_excludes_rejected() -> None:
    # The whole-event (None) path reuses the SAME effective overlay — a rejected pair is still out.
    students = [_student("a")]
    media = _media("m1", "m2")
    appearances = [
        make_appearance(student_id="a", media_id="m1", event_id="event-1"),
        make_appearance(student_id="a", media_id="m2", event_id="event-1"),
    ]
    corrections = [
        make_match_correction(
            media_id="m1", student_id="a", event_id="event-1",
            verdict=MatchVerdict.REJECTED,
        )
    ]
    gallery = _gallery(
        students=students, appearances=appearances, corrections=corrections, media=media
    )
    got = await gallery.event_photo_recipients(
        school_id="school-1", event_id="event-1", media_ids=None
    )
    assert {s.id: set(ids) for s, ids in got} == {"a": {"m2"}}  # rejected m1 out even whole-event


async def test_recipients_foreign_event_404() -> None:
    gallery = _gallery(students=[_student("a")], appearances=[], media=[])
    with pytest.raises(NotFoundError):
        await gallery.event_photo_recipients(
            school_id="school-1", event_id="OTHER-EVENT", media_ids=["m1"]
        )


# ---- WhatsAppShareService.send_event_photos (the fan-out) ----------------


async def _fanout(
    service: WhatsAppShareService, media_ids: list[str]
) -> EventPhotoSendSummary:
    return await service.send_event_photos(
        school_id="school-1",
        event_id="event-1",
        media_ids=media_ids,
        actor_user_id="actor-1",
        actor_role="school_admin",
    )


async def test_fanout_sends_each_consenting_student_their_subset() -> None:
    students = [_student("a", number="15551110001"), _student("b", number="15551110002")]
    media = _media("m1", "m2")
    appearances = [
        make_appearance(student_id="a", media_id="m1", event_id="event-1"),
        make_appearance(student_id="a", media_id="m2", event_id="event-1"),
        make_appearance(student_id="b", media_id="m2", event_id="event-1"),
    ]
    gallery = _gallery(students=students, appearances=appearances, media=media)
    service, sender, log = _share(gallery=gallery, students=students)
    summary = await _fanout(service, ["m1", "m2"])
    # a gets 2, b gets 1 → 3 photos sent to 2 students.
    assert summary.sent == 3 and summary.failed == 0
    assert summary.students_sent == 2 and summary.students_skipped == 0
    assert len(sender.sent) == 3
    # PII: no recipient number appears in any send-log row's fields (sender_number is the SENDER).
    for r in log.rows:
        assert r.sender_number != "15551110001" and r.sender_number != "15551110002"
    by_student = {r.student_id: r.sent for r in summary.results}
    assert by_student == {"a": 2, "b": 1}


async def test_fanout_whole_event_sends_all_matched() -> None:
    # media_ids=None → the whole-event announce: each appearing student gets ALL their photos.
    students = [_student("a", number="15551110001"), _student("b", number="15551110002")]
    media = _media("m1", "m2", "m3")
    appearances = [
        make_appearance(student_id="a", media_id="m1", event_id="event-1"),
        make_appearance(student_id="a", media_id="m2", event_id="event-1"),
        make_appearance(student_id="b", media_id="m3", event_id="event-1"),
    ]
    gallery = _gallery(students=students, appearances=appearances, media=media)
    service, sender, _log = _share(gallery=gallery, students=students)
    summary = await service.send_event_photos(
        school_id="school-1",
        event_id="event-1",
        media_ids=None,
        actor_user_id="actor-1",
        actor_role="school_admin",
    )
    assert summary.sent == 3 and summary.students_sent == 2
    assert {r.student_id: r.sent for r in summary.results} == {"a": 2, "b": 1}
    assert len(sender.sent) == 3


async def test_fanout_skips_non_consenting_student() -> None:
    # a is opted-in; b is not opted in; c has no number → only a receives.
    students = [
        _student("a", number="15551110001"),
        _student("b", opted_in=False),
        _student("c", number=None),
    ]
    media = _media("m1")
    appearances = [
        make_appearance(student_id="a", media_id="m1", event_id="event-1"),
        make_appearance(student_id="b", media_id="m1", event_id="event-1"),
        make_appearance(student_id="c", media_id="m1", event_id="event-1"),
    ]
    gallery = _gallery(students=students, appearances=appearances, media=media)
    service, sender, _log = _share(gallery=gallery, students=students)
    summary = await _fanout(service, ["m1"])
    assert summary.sent == 1 and summary.students_sent == 1
    assert summary.students_skipped == 2  # b + c skipped for consent
    assert len(sender.sent) == 1
    skipped = {r.student_id: r.reason for r in summary.results if r.reason is not None}
    assert set(skipped) == {"b", "c"}
    assert skipped["b"] == "not opted in" and skipped["c"] == "no mobile number"


async def test_fanout_unconfigured_platform_raises() -> None:
    students = [_student("a")]
    media = _media("m1")
    appearances = [make_appearance(student_id="a", media_id="m1", event_id="event-1")]
    gallery = _gallery(students=students, appearances=appearances, media=media)
    # No sender + no template + not interim → the whole fan-out fails cleanly.
    service, sender, _log = _share(
        gallery=gallery,
        students=students,
        platform_config=_platform_config(sender=None, template=None),
        default_sender="",
    )
    with pytest.raises(ValidationError):
        await _fanout(service, ["m1"])
    assert sender.sent == []


async def test_fanout_respects_budget_across_students() -> None:
    students = [_student("a", number="15551110001"), _student("b", number="15551110002")]
    media = _media("m1", "m2", "m3")
    appearances = [
        make_appearance(student_id="a", media_id="m1", event_id="event-1"),
        make_appearance(student_id="a", media_id="m2", event_id="event-1"),
        make_appearance(student_id="b", media_id="m3", event_id="event-1"),
    ]
    gallery = _gallery(students=students, appearances=appearances, media=media)
    # Cap = 2 → only 2 of the 3 photos actually send (the 3rd is over-budget skipped).
    service, sender, _log = _share(gallery=gallery, students=students, monthly_cap=2)
    summary = await _fanout(service, ["m1", "m2", "m3"])
    assert summary.sent == 2
    assert summary.skipped >= 1  # the over-budget photo(s)
    assert len(sender.sent) == 2  # only 2 hit the provider


async def test_fanout_interim_sends_all_to_test_number_bypassing_consent() -> None:
    # In interim mode even a not-opted-in student's photos go to the test number.
    students = [_student("a", opted_in=False, number=None)]
    media = _media("m1")
    appearances = [make_appearance(student_id="a", media_id="m1", event_id="event-1")]
    gallery = _gallery(students=students, appearances=appearances, media=media)
    service, sender, _log = _share(
        gallery=gallery,
        students=students,
        platform_config=_platform_config(interim_test_number=_TEST_NUMBER),
    )
    summary = await _fanout(service, ["m1"])
    assert summary.sent == 1 and summary.students_sent == 1
    assert len(sender.image_links) == 1  # the interim free-form path
    assert sender.image_links[0]["to"] == _TEST_NUMBER
    assert sender.sent == []  # not the template path


async def test_fanout_rejected_photo_never_sent() -> None:
    students = [_student("a", number="15551110001")]
    media = _media("m1")
    appearances = [make_appearance(student_id="a", media_id="m1", event_id="event-1")]
    corrections = [
        make_match_correction(
            media_id="m1", student_id="a", event_id="event-1",
            verdict=MatchVerdict.REJECTED,
        )
    ]
    gallery = _gallery(
        students=students, appearances=appearances, corrections=corrections, media=media
    )
    service, sender, _log = _share(gallery=gallery, students=students)
    summary = await _fanout(service, ["m1"])
    assert summary.sent == 0 and summary.students_sent == 0  # a effectively appears in nothing
    assert sender.sent == []


async def test_fanout_best_effort_on_per_student_error() -> None:
    # a & b both appear; the share service's student repo is MISSING b, so send_student_photos(b)
    # raises NotFoundError mid-loop. Best-effort: b is recorded as an error, a's photo still sends
    # (the fan-out never aborts partway).
    a = _student("a", number="15551110001")
    b = _student("b", number="15551110002")
    media = _media("m1", "m2")
    appearances = [
        make_appearance(student_id="a", media_id="m1", event_id="event-1"),
        make_appearance(student_id="b", media_id="m2", event_id="event-1"),
    ]
    gallery = _gallery(students=[a, b], appearances=appearances, media=media)
    # The share service only knows 'a' → the per-student send for b raises (caught).
    service, sender, _log = _share(gallery=gallery, students=[a])
    summary = await _fanout(service, ["m1", "m2"])
    assert summary.students_sent == 1  # a sent
    assert len(sender.sent) == 1  # only a's photo hit the provider (no partial abort)
    err = next(r for r in summary.results if r.student_id == "b")
    assert err.reason == "error" and err.sent == 0


# ---- routes: preview + send (permissions, tenant, 422) -------------------

_HASHER = Argon2PasswordHasher()


def _user(*, id: str, role: Role, school_id: str | None) -> User:
    user: User = make_user(
        id=id, school_id=school_id, email=f"{id}@x.io",
        password_hash=_HASHER.hash("pw"), role=role,
    )
    return user


def _route_client() -> TestClient:
    students = [_student("a", number="15551110001")]
    media = _media("m1")
    appearances = [make_appearance(student_id="a", media_id="m1", event_id="event-1")]
    container = SeededContainer(
        FakeUserRepo(
            [
                _user(id="sa1", role=Role.SCHOOL_ADMIN, school_id="school-1"),
                _user(id="t1", role=Role.TEACHER, school_id="school-1"),
                _user(id="pa", role=Role.PLATFORM_ADMIN, school_id=None),
                _user(id="stu", role=Role.STUDENT, school_id="school-1"),
            ]
        ),
        FakeSchoolRepo([make_school(id="school-1", name="Alpha")]),
        students=FakeStudentRepo(students),
        events=FakeEventRepo([make_event(id="event-1", school_id="school-1")]),
        media=FakeMediaRepo(media),
        ml_results_reader=FakeMlResultsReader(appearances),
        platform_config=FakePlatformConfigRepo(_platform_config()),
    )
    app = create_app()
    app.dependency_overrides[get_container_dep] = lambda: container
    return TestClient(app)


def _auth(client: TestClient, who: str) -> dict[str, str]:
    resp = client.post("/v1/auth/login", json={"email": f"{who}@x.io", "password": "pw"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_recipients_route_200_and_shape() -> None:
    client = _route_client()
    resp = client.post(
        "/v1/events/event-1/photo-recipients",
        headers=_auth(client, "sa1"),
        json={"media_ids": ["m1"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["interim"] is False  # no interim number configured
    assert len(body["recipients"]) == 1
    r = body["recipients"][0]
    assert r["student_id"] == "a" and r["photo_count"] == 1
    assert r["opted_in"] is True and r["has_number"] is True


def test_send_route_200() -> None:
    client = _route_client()
    resp = client.post(
        "/v1/events/event-1/whatsapp-send-photos",
        headers=_auth(client, "sa1"),
        json={"media_ids": ["m1"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sent"] == 1 and body["students_sent"] == 1
    # PII-free — the recipient number never appears in the response.
    assert "15551110001" not in resp.text


def test_whole_event_routes_omit_media_ids() -> None:
    # "Announce on WhatsApp" sends {} (no media_ids) → the whole event. Both routes accept it.
    client = _route_client()
    resp = client.post(
        "/v1/events/event-1/photo-recipients",
        headers=_auth(client, "sa1"),
        json={},
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["recipients"]) == 1
    resp = client.post(
        "/v1/events/event-1/whatsapp-send-photos",
        headers=_auth(client, "sa1"),
        json={},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["sent"] == 1
    # The FE sends an EXPLICIT null (JSON.stringify({media_ids: null})) — same whole-event path.
    resp = client.post(
        "/v1/events/event-1/whatsapp-send-photos",
        headers=_auth(client, "sa1"),
        json={"media_ids": None},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["sent"] == 1


def test_teacher_allowed_student_and_platform_403() -> None:
    client = _route_client()
    # Teacher (whatsapp:send) is allowed.
    resp = client.post(
        "/v1/events/event-1/photo-recipients",
        headers=_auth(client, "t1"),
        json={"media_ids": ["m1"]},
    )
    assert resp.status_code == 200, resp.text
    for who in ("stu", "pa"):
        resp = client.post(
            "/v1/events/event-1/whatsapp-send-photos",
            headers=_auth(client, who),
            json={"media_ids": ["m1"]},
        )
        assert resp.status_code == 403, f"{who}: {resp.text}"


def test_route_over_cap_is_422() -> None:
    client = _route_client()
    resp: httpx.Response = client.post(
        "/v1/events/event-1/whatsapp-send-photos",
        headers=_auth(client, "sa1"),
        json={"media_ids": [f"m{i}" for i in range(1001)]},
    )
    assert resp.status_code == 422, resp.text


def test_route_empty_media_ids_is_422() -> None:
    client = _route_client()
    resp = client.post(
        "/v1/events/event-1/photo-recipients",
        headers=_auth(client, "sa1"),
        json={"media_ids": []},
    )
    assert resp.status_code == 422, resp.text


def test_recipients_foreign_event_404_over_route() -> None:
    client = _route_client()
    resp = client.post(
        "/v1/events/NOPE/photo-recipients",
        headers=_auth(client, "sa1"),
        json={"media_ids": ["m1"]},
    )
    assert resp.status_code == 404, resp.text


# ---- per-photo "sent on WhatsApp N times" count -------------------------


def test_media_whatsapp_log_counts_sent() -> None:
    # Before any send → 0; after sending the photo to the student → 1 (each send = one message).
    client = _route_client()
    resp = client.get("/v1/media/m1/whatsapp-log", headers=_auth(client, "sa1"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["sent_count"] == 0
    send = client.post(
        "/v1/events/event-1/whatsapp-send-photos",
        headers=_auth(client, "sa1"),
        json={"media_ids": ["m1"]},
    )
    assert send.status_code == 200 and send.json()["sent"] == 1, send.text
    resp = client.get("/v1/media/m1/whatsapp-log", headers=_auth(client, "sa1"))
    assert resp.json()["sent_count"] == 1


def test_media_whatsapp_log_permissions() -> None:
    # gallery:view_all (staff) reads it; a student / platform admin is 403.
    client = _route_client()
    assert (
        client.get("/v1/media/m1/whatsapp-log", headers=_auth(client, "t1")).status_code
        == 200
    )
    for who in ("stu", "pa"):
        resp = client.get("/v1/media/m1/whatsapp-log", headers=_auth(client, who))
        assert resp.status_code == 403, f"{who}: {resp.text}"
