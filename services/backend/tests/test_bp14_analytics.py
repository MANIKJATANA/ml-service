"""BP14 — program analytics & trends (decisions/0062).

The ``AnalyticsService`` compositions — the school program view (delivery/sign-in/engagement
numerators + per-term rollups + monthly trend, tenant-isolated) and the estate adoption funnel
(per-school counts + the stalled/idle heuristic) — plus the ``last_login_at`` sign-in signal
(stamped on login, never on refresh) and the two routes end-to-end (permission-gated, tenant
from the token).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.domain.errors import NotFoundError
from backend.domain.models import (
    EnrollmentStatus,
    Role,
    User,
    WhatsAppSendLogEntry,
)
from backend.main import create_app
from backend.services.analytics_service import AnalyticsService
from backend_fakes import (
    FakeDownloadAuditRepo,
    FakeEventRepo,
    FakeMatchCorrectionRepo,
    FakeMediaRepo,
    FakeNotificationReadRepo,
    FakeSchoolRepo,
    FakeStudentRepo,
    FakeUserRepo,
    FakeWhatsAppSendLogRepo,
    SeededContainer,
    make_event,
    make_media,
    make_school,
    make_student,
    make_user,
)
from fastapi.testclient import TestClient

_S1 = "s1"
_S2 = "s2"
# A created_at that is always inside the 30-day "recent" window (vs the real now the service
# uses); the default fake _NOW (2026-01-01) is deliberately outside it.
_RECENT = datetime(2099, 1, 1, tzinfo=UTC)


# ---- school analytics (service) ----------------------------------------


def _school_svc(
    *,
    users: FakeUserRepo,
    students: FakeStudentRepo,
    events: FakeEventRepo,
    media: FakeMediaRepo,
    reads: FakeNotificationReadRepo,
    schools: FakeSchoolRepo | None = None,
    corrections: FakeMatchCorrectionRepo | None = None,
    audit: FakeDownloadAuditRepo | None = None,
    whatsapp_send_log: FakeWhatsAppSendLogRepo | None = None,
) -> AnalyticsService:
    return AnalyticsService(
        schools or FakeSchoolRepo([make_school(id=_S1)]),
        users,
        students,
        events,
        media,
        reads,
        corrections or FakeMatchCorrectionRepo(),
        audit or FakeDownloadAuditRepo(),
        whatsapp_send_log or FakeWhatsAppSendLogRepo(),
    )


async def test_school_analytics_composes_rates_terms_and_trend() -> None:
    users = FakeUserRepo(
        [make_user(id=f"u{i}", school_id=_S1, role=Role.STUDENT, email=f"u{i}@x.io")
         for i in range(4)]
    )
    # 3 of 4 student logins have signed in.
    for uid in ("u0", "u1", "u2"):
        await users.touch_last_login(uid)
    students = FakeStudentRepo(
        [
            make_student(id="a", school_id=_S1, enrollment_status=EnrollmentStatus.ENROLLED),
            make_student(id="b", school_id=_S1, enrollment_status=EnrollmentStatus.ENROLLED),
            make_student(id="c", school_id=_S1, enrollment_status=EnrollmentStatus.PENDING),
            make_student(id="d", school_id=_S1, enrollment_status=EnrollmentStatus.FAILED),
        ]
    )
    events = FakeEventRepo(
        [
            # Term 1: 2 events, one announced (notified). The monthly trend buckets by
            # event_date (when the event happened), not the created row time.
            make_event(id="e1", school_id=_S1, term="Term 1", notified_at=_RECENT,
                       event_date=date(2026, 3, 1)),
            make_event(id="e2", school_id=_S1, term="Term 1", auto_notify=False,
                       event_date=date(2026, 4, 1)),
            # Term 2: 1 event, auto-announced (auto_notify + completed).
            make_event(id="e3", school_id=_S1, term="Term 2", auto_notify=True,
                       completed_at=_RECENT, event_date=date(2026, 4, 15)),
            # An untagged event — counted in totals, excluded from per-term.
            make_event(id="e4", school_id=_S1, term=None, auto_notify=False,
                       event_date=date(2026, 3, 20)),
        ]
    )
    media = FakeMediaRepo(
        [
            make_media(id="m1", school_id=_S1, event_id="e1"),
            make_media(id="m2", school_id=_S1, event_id="e1"),
            make_media(id="m3", school_id=_S1, event_id="e3"),
        ]
    )
    reads = FakeNotificationReadRepo()
    reads.set_seen("a", "e1", _RECENT)
    reads.set_seen("a", "e3", _RECENT)  # same student twice -> counts once
    reads.set_seen("b", "e1", _RECENT)

    a = await _school_svc(
        users=users, students=students, events=events, media=media, reads=reads
    ).school_analytics(school_id=_S1)

    assert a.students_total == 4
    assert a.students_enrolled == 2
    assert a.students_signed_in == 3
    assert a.students_engaged == 2  # a + b (a's two reads collapse)
    assert a.events_total == 4
    assert a.events_distributed == 2  # e1 (notified) + e3 (auto+completed)
    assert a.photos_total == 3
    # Per-term: Term 1 (2 events, 2 photos, 1 announced), Term 2 (1 event, 1 photo, 1 announced).
    terms = {t.term: t for t in a.terms}
    assert set(terms) == {"Term 1", "Term 2"}
    t1, t2 = terms["Term 1"], terms["Term 2"]
    assert (t1.events, t1.photos, t1.distributed) == (2, 2, 1)
    assert (t2.events, t2.photos, t2.distributed) == (1, 1, 1)
    # Trend: events per event_date month (2026-03: e1+e4=2, 2026-04: e2+e3=2), photos in
    # 2026-01 (media upload default _NOW). Months are sorted ascending.
    by_month = {m.month: m for m in a.months}
    assert by_month["2026-03"].events == 2
    assert by_month["2026-04"].events == 2
    assert list(m.month for m in a.months) == sorted(m.month for m in a.months)


async def test_school_analytics_is_tenant_isolated() -> None:
    users = FakeUserRepo(
        [
            make_user(id="s1u", school_id=_S1, role=Role.STUDENT, email="s1u@x.io"),
            make_user(id="s2u", school_id=_S2, role=Role.STUDENT, email="s2u@x.io"),
        ]
    )
    await users.touch_last_login("s2u")  # only the OTHER school signed in
    students = FakeStudentRepo(
        [
            make_student(id="a", school_id=_S1, enrollment_status=EnrollmentStatus.PENDING),
            make_student(id="b", school_id=_S2, enrollment_status=EnrollmentStatus.ENROLLED),
        ]
    )
    events = FakeEventRepo(
        [
            make_event(id="e1", school_id=_S1, term="T", notified_at=_RECENT),
            make_event(id="ef", school_id=_S2, term="T", notified_at=_RECENT),
        ]
    )
    media = FakeMediaRepo([make_media(id="mf", school_id=_S2, event_id="ef")])
    a = await _school_svc(
        users=users, students=students, events=events, media=media,
        reads=FakeNotificationReadRepo(),
    ).school_analytics(school_id=_S1)
    assert a.students_total == 1  # only s1
    assert a.students_signed_in == 0  # s2u's sign-in never leaks
    assert a.events_total == 1
    assert a.photos_total == 0  # s2's photo never leaks


async def test_school_analytics_missing_school_raises_not_found() -> None:
    svc = _school_svc(
        users=FakeUserRepo(), students=FakeStudentRepo(), events=FakeEventRepo(),
        media=FakeMediaRepo(), reads=FakeNotificationReadRepo(),
        schools=FakeSchoolRepo(),  # empty
    )
    with pytest.raises(NotFoundError):
        await svc.school_analytics(school_id="ghost")


async def test_school_analytics_empty_school_returns_zeros() -> None:
    # A brand-new school (only a schools row) — the day-one path must not crash or KeyError.
    a = await _school_svc(
        users=FakeUserRepo(), students=FakeStudentRepo(), events=FakeEventRepo(),
        media=FakeMediaRepo(), reads=FakeNotificationReadRepo(),
    ).school_analytics(school_id=_S1)
    assert a.students_total == 0
    assert a.students_enrolled == 0
    assert a.students_signed_in == 0
    assert a.students_engaged == 0
    assert a.events_total == 0
    assert a.events_distributed == 0
    assert a.photos_total == 0
    assert a.terms == ()
    assert a.months == ()


async def test_blank_or_whitespace_term_is_treated_as_untagged() -> None:
    events = FakeEventRepo(
        [
            make_event(id="e1", school_id=_S1, term="Term 1"),
            make_event(id="e2", school_id=_S1, term=""),  # blank
            make_event(id="e3", school_id=_S1, term="   "),  # whitespace
        ]
    )
    a = await _school_svc(
        users=FakeUserRepo(), students=FakeStudentRepo(), events=events,
        media=FakeMediaRepo(), reads=FakeNotificationReadRepo(),
    ).school_analytics(school_id=_S1)
    assert [t.term for t in a.terms] == ["Term 1"]  # blank/whitespace excluded
    assert a.events_total == 3  # but all three still count in the totals


async def test_trend_caps_at_12_months_and_sorts_across_year_boundary() -> None:
    # 14 distinct months spanning a year boundary -> the trend keeps the most recent 12,
    # ascending (a lexical 'YYYY-MM' sort == chronological).
    ym = [(2025, m) for m in range(1, 13)] + [(2026, 1), (2026, 2)]
    events = FakeEventRepo(
        [
            make_event(id=f"e{i}", school_id=_S1, event_date=date(y, m, 1))
            for i, (y, m) in enumerate(ym)
        ]
    )
    a = await _school_svc(
        users=FakeUserRepo(), students=FakeStudentRepo(), events=events,
        media=FakeMediaRepo(), reads=FakeNotificationReadRepo(),
    ).school_analytics(school_id=_S1)
    labels = [m.month for m in a.months]
    assert len(labels) == 12
    assert labels[0] == "2025-03"  # the two oldest (2025-01, 2025-02) are dropped
    assert labels[-1] == "2026-02"
    assert labels == sorted(labels)


async def test_login_survives_touch_last_login_failure() -> None:
    # The BP14 sign-in write is best-effort: a DB blip stamping last_login must NOT fail login.
    users = FakeUserRepo([_student_user()])

    async def _boom(_user_id: str) -> None:
        raise RuntimeError("db blip")

    users.touch_last_login = _boom
    auth = _container_for_login(users).auth_service()
    result = await auth.login(email="stu@x.io", password="pw")
    assert result.tokens.access_token  # login still succeeded


# ---- estate analytics (service) ----------------------------------------


async def test_estate_analytics_funnel_stalled_and_idle() -> None:
    schools = FakeSchoolRepo(
        [
            make_school(id="healthy", name="Riverside"),
            make_school(id="stalled", name="Greenfield"),
            make_school(id="idle", name="Maple"),
            make_school(id="empty", name="New School"),
        ]
    )
    users = FakeUserRepo(
        [
            make_user(id="ht", school_id="healthy", role=Role.TEACHER, email="ht@x.io"),
            make_user(id="hs", school_id="healthy", role=Role.STUDENT, email="hs@x.io"),
        ]
    )
    await users.touch_last_login("hs")  # a signed-in student at the healthy school
    students = FakeStudentRepo(
        [
            make_student(id="h1", school_id="healthy", enrollment_status=EnrollmentStatus.ENROLLED),
            # stalled: students imported, none enrolled
            make_student(id="g1", school_id="stalled", enrollment_status=EnrollmentStatus.PENDING),
            make_student(id="g2", school_id="stalled", enrollment_status=EnrollmentStatus.PENDING),
            # idle: enrolled but no recent event
            make_student(id="m1", school_id="idle", enrollment_status=EnrollmentStatus.ENROLLED),
        ]
    )
    events = FakeEventRepo(
        [
            make_event(id="he", school_id="healthy", notified_at=_RECENT, created_at=_RECENT),
            # idle school's only event is old (default _NOW, outside the 30-day window)
            make_event(id="me", school_id="idle", auto_notify=False),
        ]
    )
    estate = await AnalyticsService(
        schools,
        users,
        students,
        events,
        FakeMediaRepo(),
        FakeNotificationReadRepo(),
        FakeMatchCorrectionRepo(),
        FakeDownloadAuditRepo(),
        FakeWhatsAppSendLogRepo(),
    ).estate_analytics()

    by_id = {f.school_id: f for f in estate.schools}
    assert by_id["healthy"].teachers == 1
    assert by_id["healthy"].enrolled == 1
    assert by_id["healthy"].signed_in_students == 1
    assert by_id["healthy"].distributed == 1
    assert not by_id["healthy"].stalled and not by_id["healthy"].idle
    # stalled: students>0, enrolled==0
    assert by_id["stalled"].students == 2 and by_id["stalled"].enrolled == 0
    assert by_id["stalled"].stalled and not by_id["stalled"].idle
    # idle: enrolled>0 but no recent event
    assert by_id["idle"].enrolled == 1 and not by_id["idle"].stalled
    assert by_id["idle"].idle
    # empty school: no students -> neither flag
    assert not by_id["empty"].stalled and not by_id["empty"].idle

    assert estate.total_schools == 4
    assert estate.total_students == 4
    assert estate.total_enrolled == 2
    assert estate.total_events == 2
    assert estate.stalled_schools == 1
    assert estate.idle_schools == 1


# ---- sign-in signal (auth) ---------------------------------------------

_HASHER = Argon2PasswordHasher()


def _student_user() -> User:
    user: User = make_user(
        id="stu", school_id=_S1, role=Role.STUDENT, email="stu@x.io",
        password_hash=_HASHER.hash("pw"),
    )
    return user


def _container_for_login(users: FakeUserRepo) -> SeededContainer:
    return SeededContainer(
        users,
        FakeSchoolRepo([make_school(id=_S1)]),
        students=FakeStudentRepo([make_student(id="st", school_id=_S1, user_id="stu")]),
    )


async def test_login_stamps_last_login_refresh_does_not() -> None:
    users = FakeUserRepo([_student_user()])
    auth = _container_for_login(users).auth_service()
    assert await users.count_signed_in_by_school_and_role(_S1, Role.STUDENT) == 0

    result = await auth.login(email="stu@x.io", password="pw")
    assert await users.count_signed_in_by_school_and_role(_S1, Role.STUDENT) == 1

    # A refresh is not an interactive sign-in — it must not stamp.
    users._signed_in.clear()
    await auth.refresh(refresh_token=result.tokens.refresh_token)
    assert await users.count_signed_in_by_school_and_role(_S1, Role.STUDENT) == 0


# ---- routes -------------------------------------------------------------


def _u(*, id: str, role: Role, school_id: str | None, email: str) -> User:
    user: User = make_user(
        id=id, school_id=school_id, email=email,
        password_hash=_HASHER.hash("pw"), role=role,
    )
    return user


def _status(client: TestClient, path: str, who: str | None) -> int:
    headers = _auth(_token(client, who)) if who is not None else {}
    return int(client.get(path, headers=headers).status_code)


def _build() -> TestClient:
    container = SeededContainer(
        FakeUserRepo(
            [
                _u(id="sa", role=Role.SCHOOL_ADMIN, school_id=_S1, email="sa@x.io"),
                _u(id="te", role=Role.TEACHER, school_id=_S1, email="te@x.io"),
                _u(id="stu", role=Role.STUDENT, school_id=_S1, email="stu@x.io"),
                _u(id="pa", role=Role.PLATFORM_ADMIN, school_id=None, email="pa@x.io"),
            ]
        ),
        FakeSchoolRepo([make_school(id=_S1)]),
        students=FakeStudentRepo(
            [make_student(id="st1", school_id=_S1, user_id="stu",
                          enrollment_status=EnrollmentStatus.ENROLLED)]
        ),
        events=FakeEventRepo([make_event(id="e1", school_id=_S1, term="T", notified_at=_RECENT)]),
        media=FakeMediaRepo([make_media(id="m1", school_id=_S1, event_id="e1")]),
    )
    app = create_app()
    app.dependency_overrides[get_container_dep] = lambda: container
    return TestClient(app)


def _token(client: TestClient, who: str) -> str:
    resp = client.post("/v1/auth/login", json={"email": f"{who}@x.io", "password": "pw"})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def _auth(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


def test_school_analytics_route_shape_and_perms() -> None:
    client = _build()
    resp = client.get("/v1/analytics/school", headers=_auth(_token(client, "sa")))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["school_name"]
    assert body["events_total"] == 1
    assert body["events_distributed"] == 1
    assert body["students_enrolled"] == 1
    assert {"term", "events", "photos", "distributed"} <= set(body["terms"][0])

    # teacher may view; student + platform may not; no token -> 401.
    assert _status(client, "/v1/analytics/school", "te") == 200
    assert _status(client, "/v1/analytics/school", "stu") == 403
    assert _status(client, "/v1/analytics/school", "pa") == 403
    assert _status(client, "/v1/analytics/school", None) == 401


def test_estate_analytics_route_is_platform_only() -> None:
    client = _build()
    resp = client.get("/v1/analytics/estate", headers=_auth(_token(client, "pa")))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_schools"] == 1
    assert isinstance(body["schools"], list)
    assert {"school_id", "stalled", "idle", "enrolled"} <= set(body["schools"][0])

    # a school admin / teacher / no-token may not reach the estate view.
    assert _status(client, "/v1/analytics/estate", "sa") == 403
    assert _status(client, "/v1/analytics/estate", "te") == 403
    assert _status(client, "/v1/analytics/estate", None) == 401


def test_login_route_reflects_in_analytics_signin_count() -> None:
    client = _build()
    # Before the student logs in, sign-in count is 0.
    before = client.get("/v1/analytics/school", headers=_auth(_token(client, "sa")))
    assert before.json()["students_signed_in"] == 0
    # The student logs in (stamps last_login), then the admin's analytics reflects it.
    _token(client, "stu")
    after = client.get("/v1/analytics/school", headers=_auth(_token(client, "sa")))
    assert after.json()["students_signed_in"] == 1


def _wa_row(school_id: str, status: str, at: datetime) -> WhatsAppSendLogEntry:
    """One whatsapp_send_log row for the estate cost test (PII-free — no recipient number)."""
    return WhatsAppSendLogEntry(
        id=f"wa-{school_id}-{status}-{at.timestamp()}",
        school_id=school_id,
        student_id=None,
        media_id="m1",
        actor_user_id=None,
        actor_role="school_admin",
        sender_number="15551234567",
        status=status,
        provider_message_id=None,
        error=None,
        created_at=at,
    )


async def test_estate_whatsapp_sent_counts() -> None:
    # Per-school WhatsApp cost: all-time + this UTC month; only 'sent' rows count; totals sum.
    now = datetime.now(UTC)
    before_month = datetime(now.year, now.month, 1, tzinfo=UTC) - timedelta(days=1)
    wa = FakeWhatsAppSendLogRepo(
        [
            _wa_row("s1", "sent", now),
            _wa_row("s1", "sent", now),
            _wa_row("s1", "sent", now),
            _wa_row("s1", "sent", before_month),  # counts all-time, NOT this month
            _wa_row("s1", "failed", now),  # never counted
            _wa_row("s1", "skipped", now),  # never counted
            _wa_row("s2", "sent", now),
        ]
    )
    estate = await AnalyticsService(
        FakeSchoolRepo([make_school(id="s1"), make_school(id="s2")]),
        FakeUserRepo(),
        FakeStudentRepo(),
        FakeEventRepo(),
        FakeMediaRepo(),
        FakeNotificationReadRepo(),
        FakeMatchCorrectionRepo(),
        FakeDownloadAuditRepo(),
        wa,
    ).estate_analytics()

    by = {f.school_id: f for f in estate.schools}
    assert by["s1"].whatsapp_sent == 4 and by["s1"].whatsapp_sent_month == 3
    assert by["s2"].whatsapp_sent == 1 and by["s2"].whatsapp_sent_month == 1
    assert estate.whatsapp_sent_total == 5
    assert estate.whatsapp_sent_month_total == 4
