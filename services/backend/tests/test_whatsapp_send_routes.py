"""End-to-end WhatsApp send routes over HTTP (W2).

Real JWT + argon2 + RBAC + WhatsAppShareService; fake repos/store/sender injected via a
SeededContainer. Exercises the happy path (200 + per-media results, the fake sender records the
send), tenant isolation (a foreign student → 404, nothing sent), the permission matrix (teacher
allowed; student + platform admin 403), and the documented 4xx (not-opted-in / disabled).
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.adapters.whatsapp.fake_sender import FakeWhatsAppSender
from backend.api.deps import get_container_dep
from backend.domain.models import (
    Appearance,
    MatchCorrection,
    MatchVerdict,
    Media,
    PlatformConfig,
    Role,
    User,
)
from backend.main import create_app
from backend_fakes import (
    FakeEventRepo,
    FakeMatchCorrectionRepo,
    FakeMediaRepo,
    FakeMlResultsReader,
    FakePlatformConfigRepo,
    FakeSchoolRepo,
    FakeStudentRepo,
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

_HASHER = Argon2PasswordHasher()
_MOBILE = "15559990000"
_SENDER = "15551234567"
_TEMPLATE = "photo_notice"


def _user(*, id: str, role: Role, school_id: str | None) -> User:
    user: User = make_user(
        id=id,
        school_id=school_id,
        email=f"{id}@x.io",
        password_hash=_HASHER.hash("pw"),
        role=role,
    )
    return user


def _platform_config(
    *, sender: str | None = _SENDER, template: str | None = _TEMPLATE
) -> PlatformConfig:
    # 0099: the platform config is the SOLE WhatsApp config (sender phone-number ID + template).
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return PlatformConfig(
        id="platform",
        meta_access_token=None,
        sender_number=sender,
        template_name=template,
        interim_test_number=None,
        interim_mode=False,
        created_at=now,
        updated_at=now,
    )


def _build(
    *,
    users: list[User] | None = None,
    students: FakeStudentRepo | None = None,
    appearances: list[Appearance] | None = None,
    corrections: list[MatchCorrection] | None = None,
    media: list[Media] | None = None,
    configured: bool = True,
    sender: FakeWhatsAppSender | None = None,
) -> tuple[TestClient, SeededContainer, FakeWhatsAppSender]:
    fake_sender = sender or FakeWhatsAppSender()
    container = SeededContainer(
        FakeUserRepo(
            users
            or [
                _user(id="sa1", role=Role.SCHOOL_ADMIN, school_id="s1"),
                _user(id="t1", role=Role.TEACHER, school_id="s1"),
                _user(id="pa", role=Role.PLATFORM_ADMIN, school_id=None),
                _user(id="stu-login", role=Role.STUDENT, school_id="s1"),
            ]
        ),
        FakeSchoolRepo([make_school(id="s1", name="Alpha"), make_school(id="s2")]),
        students=students
        or FakeStudentRepo(
            [
                make_student(
                    id="stu-1",
                    school_id="s1",
                    user_id="stu-login",
                    mobile_number=_MOBILE,
                    whatsapp_opt_in=True,
                )
            ]
        ),
        events=FakeEventRepo([make_event(id="event-1", school_id="s1")]),
        media=FakeMediaRepo(media or [make_media(id="m1", school_id="s1", event_id="event-1")]),
        ml_results_reader=FakeMlResultsReader(
            appearances
            or [make_appearance(student_id="stu-1", media_id="m1", event_id="event-1")]
        ),
        match_corrections=FakeMatchCorrectionRepo(corrections or []),
        platform_config=FakePlatformConfigRepo(
            _platform_config() if configured else _platform_config(sender=None, template=None)
        ),
        whatsapp_sender=fake_sender,
        whatsapp_send_log=FakeWhatsAppSendLogRepo(),
    )
    app = create_app()
    app.dependency_overrides[get_container_dep] = lambda: container
    return TestClient(app), container, fake_sender


def _auth(client: TestClient, who: str) -> dict[str, str]:
    resp = client.post("/v1/auth/login", json={"email": f"{who}@x.io", "password": "pw"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _send(
    client: TestClient,
    hdr: dict[str, str],
    sid: str = "stu-1",
    media_ids: list[str] | None = None,
) -> httpx.Response:
    body: dict[str, object] = {}
    if media_ids is not None:
        body["media_ids"] = media_ids
    resp: httpx.Response = client.post(
        f"/v1/students/{sid}/whatsapp-send", headers=hdr, json=body
    )
    return resp


# ---- happy path ---------------------------------------------------------


def test_send_happy_path_200_with_results() -> None:
    client, _c, sender = _build()
    resp = _send(client, _auth(client, "sa1"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sent"] == 1 and body["failed"] == 0 and body["skipped"] == 0
    assert [r["media_id"] for r in body["results"]] == ["m1"]
    assert body["results"][0]["status"] == "sent"
    # The fake sender actually received the send, to the recipient's real number.
    assert len(sender.sent) == 1
    assert sender.sent[0].to == _MOBILE
    assert sender.sent[0].sender_number == _SENDER
    assert sender.sent[0].template_name == _TEMPLATE
    # The API response never carries the phone number (PII-free).
    assert _MOBILE not in resp.text


def test_selected_subset_only() -> None:
    media = [
        make_media(id="m1", school_id="s1", event_id="event-1"),
        make_media(id="m2", school_id="s1", event_id="event-1"),
    ]
    appearances = [
        make_appearance(student_id="stu-1", media_id="m1", event_id="event-1"),
        make_appearance(student_id="stu-1", media_id="m2", event_id="event-1"),
    ]
    client, _c, sender = _build(media=media, appearances=appearances)
    resp = _send(client, _auth(client, "sa1"), media_ids=["m1"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["sent"] == 1
    assert len(sender.sent) == 1


# ---- tenant isolation ---------------------------------------------------


def test_foreign_student_is_404_and_nothing_sent() -> None:
    # An admin in s2 tries to send stu-1 (which lives in s1) → 404, no send.
    users = [
        _user(id="sa1", role=Role.SCHOOL_ADMIN, school_id="s1"),
        _user(id="sa2", role=Role.SCHOOL_ADMIN, school_id="s2"),
        _user(id="stu-login", role=Role.STUDENT, school_id="s1"),
    ]
    client, _c, sender = _build(users=users)
    resp = _send(client, _auth(client, "sa2"))
    assert resp.status_code == 404, resp.text
    assert sender.sent == []


# ---- permission matrix --------------------------------------------------


def test_teacher_is_allowed() -> None:
    client, _c, sender = _build()
    resp = _send(client, _auth(client, "t1"))
    assert resp.status_code == 200, resp.text
    assert len(sender.sent) == 1


def test_student_is_403() -> None:
    client, _c, sender = _build()
    hdr = _auth(client, "stu-login")
    resp = _send(client, hdr)
    assert resp.status_code == 403, resp.text
    assert sender.sent == []


def test_platform_admin_is_403() -> None:
    client, _c, sender = _build()
    resp = _send(client, _auth(client, "pa"))
    assert resp.status_code == 403, resp.text
    assert sender.sent == []


# ---- documented 4xx -----------------------------------------------------


def test_not_opted_in_is_400() -> None:
    students = FakeStudentRepo(
        [
            make_student(
                id="stu-1",
                school_id="s1",
                user_id="stu-login",
                mobile_number=_MOBILE,
                whatsapp_opt_in=False,
            )
        ]
    )
    client, _c, sender = _build(students=students)
    resp = _send(client, _auth(client, "sa1"))
    assert resp.status_code == 400, resp.text
    assert sender.sent == []


def test_no_number_is_400() -> None:
    students = FakeStudentRepo(
        [
            make_student(
                id="stu-1",
                school_id="s1",
                user_id="stu-login",
                mobile_number=None,
                whatsapp_opt_in=True,
            )
        ]
    )
    client, _c, sender = _build(students=students)
    resp = _send(client, _auth(client, "sa1"))
    assert resp.status_code == 400, resp.text
    assert sender.sent == []


def test_unconfigured_platform_is_400() -> None:
    # 0099: WhatsApp is configured platform-side (no per-school enable). With no sender/template
    # set at Platform → WhatsApp, a send fails fast with 400 and nothing is sent.
    client, _c, sender = _build(configured=False)
    resp = _send(client, _auth(client, "sa1"))
    assert resp.status_code == 400, resp.text
    assert sender.sent == []


def test_rejected_appearance_is_never_sent_over_route() -> None:
    corrections = [
        make_match_correction(
            media_id="m1",
            student_id="stu-1",
            event_id="event-1",
            verdict=MatchVerdict.REJECTED,
        )
    ]
    client, _c, sender = _build(corrections=corrections)
    resp = _send(client, _auth(client, "sa1"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["sent"] == 0
    assert sender.sent == []


def test_over_cap_media_ids_is_422() -> None:
    client, _c, _sender = _build()
    resp = _send(client, _auth(client, "sa1"), media_ids=[f"m{i}" for i in range(1001)])
    assert resp.status_code == 422, resp.text


def test_unauthenticated_is_401() -> None:
    client, _c, _sender = _build()
    resp = _send(client, {})
    assert resp.status_code == 401, resp.text
