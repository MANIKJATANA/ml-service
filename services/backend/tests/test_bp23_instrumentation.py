"""BP23 — run it on numbers (decisions/0078).

The instrumentation phase's four groups: attribution (media.uploaded_by plumb, last_login_at
exposure, created_by_email), the flagship metrics (event-reach / savers / first-open trend /
quality), the answers-behind-the-numbers (never-signed-in/never-opened filters, the per-student
engagement endpoint, the roster's first-seen + downloads), and the estate age axis. Composition
+ tenant isolation + the no-cross-seam rule (every new number is over backend-owned rows).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.domain.errors import NotFoundError
from backend.domain.models import (
    EnrollmentStatus,
    MatchVerdict,
    MediaType,
    Role,
    User,
)
from backend.main import create_app
from backend.services.analytics_service import AnalyticsService
from backend.services.engagement_service import EngagementService
from backend.services.event_service import EventService
from backend.services.media_service import MediaService
from backend.services.notification_service import NotificationService
from backend_fakes import (
    FakeDownloadAuditRepo,
    FakeEventCategoryRepo,
    FakeEventJobProducer,
    FakeEventRepo,
    FakeMatchCorrectionRepo,
    FakeMediaRepo,
    FakeMlResultsReader,
    FakeNotificationChannel,
    FakeNotificationReadRepo,
    FakeObjectStore,
    FakeSchoolRepo,
    FakeStudentGroupRepo,
    FakeStudentRepo,
    FakeThumbnailer,
    FakeUserRepo,
    FakeWhatsAppSendLogRepo,
    SeededContainer,
    make_appearance,
    make_download_audit_entry,
    make_event,
    make_match_correction,
    make_school,
    make_student,
    make_user,
)
from fastapi.testclient import TestClient

_S1 = "s1"
_S2 = "s2"
_HASHER = Argon2PasswordHasher()


# ======================================================================
# A · attribution
# ======================================================================


async def test_register_media_stamps_uploaded_by() -> None:
    """The register plumb records the acting uploader on the media row (BP23)."""
    events = FakeEventRepo([make_event(id="e1", school_id=_S1)])
    media = FakeMediaRepo()
    svc = MediaService(
        media,
        events,
        FakeObjectStore(),
        FakeThumbnailer(),
        event_media_prefix="events",
    )
    got = await svc.register_media(
        school_id=_S1,
        event_id="e1",
        storage_path="events/s1/e1/photo.jpg",
        media_type=MediaType.IMAGE,
        uploaded_by="uploader-1",
    )
    assert got.uploaded_by == "uploader-1"
    # And it defaults to None when unattributed (a legacy/None caller).
    got2 = await svc.register_media(
        school_id=_S1,
        event_id="e1",
        storage_path="events/s1/e1/other.jpg",
        media_type=MediaType.IMAGE,
    )
    assert got2.uploaded_by is None


def _event_svc(*, users: FakeUserRepo, events: FakeEventRepo) -> EventService:
    return EventService(
        events,
        FakeMediaRepo(),
        FakeEventJobProducer(),
        FakeEventCategoryRepo(),
        FakeStudentGroupRepo(),
        users,
    )


async def test_event_detail_resolves_created_by_email() -> None:
    """get_event_detail resolves the creator's email in-Python; None when absent."""
    users = FakeUserRepo(
        [make_user(id="creator", school_id=_S1, email="creator@x.io")]
    )
    events = FakeEventRepo(
        [
            make_event(id="e1", school_id=_S1, created_by="creator"),
            make_event(id="e2", school_id=_S1, created_by=None),  # system event
            make_event(id="e3", school_id=_S1, created_by="ghost"),  # since-deleted
        ]
    )
    svc = _event_svc(users=users, events=events)
    assert (
        await svc.get_event_detail(school_id=_S1, event_id="e1")
    ).created_by_email == "creator@x.io"
    assert (
        await svc.get_event_detail(school_id=_S1, event_id="e2")
    ).created_by_email is None
    assert (
        await svc.get_event_detail(school_id=_S1, event_id="e3")
    ).created_by_email is None


# ======================================================================
# B · flagship metrics
# ======================================================================


def _analytics(
    *,
    schools: FakeSchoolRepo,
    users: FakeUserRepo | None = None,
    students: FakeStudentRepo | None = None,
    events: FakeEventRepo | None = None,
    media: FakeMediaRepo | None = None,
    reads: FakeNotificationReadRepo | None = None,
    corrections: FakeMatchCorrectionRepo | None = None,
    audit: FakeDownloadAuditRepo | None = None,
    whatsapp_send_log: FakeWhatsAppSendLogRepo | None = None,
) -> AnalyticsService:
    return AnalyticsService(
        schools,
        users or FakeUserRepo(),
        students or FakeStudentRepo(),
        events or FakeEventRepo(),
        media or FakeMediaRepo(),
        reads or FakeNotificationReadRepo(),
        corrections or FakeMatchCorrectionRepo(),
        audit or FakeDownloadAuditRepo(),
        whatsapp_send_log or FakeWhatsAppSendLogRepo(),
    )


async def test_school_analytics_reach_savers_and_quality() -> None:
    """Event-reach (distinct opened events), distinct savers, and the quality verdict trend."""
    students = FakeStudentRepo(
        [
            make_student(id="st1", school_id=_S1, user_id="u1",
                         enrollment_status=EnrollmentStatus.ENROLLED),
            make_student(id="st2", school_id=_S1, user_id="u2",
                         enrollment_status=EnrollmentStatus.ENROLLED),
        ]
    )
    events = FakeEventRepo(
        [
            make_event(id="e1", school_id=_S1, notified_at=datetime(2026, 3, 1, tzinfo=UTC)),
            make_event(id="e2", school_id=_S1, notified_at=datetime(2026, 3, 2, tzinfo=UTC)),
        ]
    )
    reads = FakeNotificationReadRepo()
    reads.set_seen("st1", "e1", datetime(2026, 3, 5, tzinfo=UTC))  # e1 opened
    reads.set_seen("st1", "e2", datetime(2026, 3, 6, tzinfo=UTC))  # e2 opened (2 distinct)
    audit = FakeDownloadAuditRepo(
        [
            make_download_audit_entry(id="a1", school_id=_S1, subject_student_id="st1"),
            make_download_audit_entry(id="a2", school_id=_S1, subject_student_id="st1"),
            # a staff download (subject None) must NOT count as a saver
            make_download_audit_entry(id="a3", school_id=_S1, subject_student_id=None),
        ]
    )
    corrections = FakeMatchCorrectionRepo(
        [
            make_match_correction(media_id="m1", student_id="st1",
                                  verdict=MatchVerdict.CONFIRMED),
            make_match_correction(media_id="m2", student_id="st2",
                                  verdict=MatchVerdict.REJECTED),
            make_match_correction(media_id="m3", student_id="st1",
                                  verdict=MatchVerdict.ADDED),
        ]
    )
    svc = _analytics(
        schools=FakeSchoolRepo([make_school(id=_S1)]),
        students=students,
        events=events,
        reads=reads,
        corrections=corrections,
        audit=audit,
    )
    a = await svc.school_analytics(school_id=_S1)

    assert a.events_distributed == 2
    assert a.events_opened == 2  # both events had an opener
    assert a.students_saved == 1  # only st1 self-downloaded; the staff download excluded
    # quality: one month, confirmed=1 / rejected=1 / added=1 (added is its own signal)
    assert len(a.quality) == 1
    q = a.quality[0]
    assert (q.confirmed, q.rejected, q.added) == (1, 1, 1)


async def test_event_reach_intersects_announced_and_opened() -> None:
    """Reach = announced ∩ opened (in-Python, seam-free) — it never over-reports an event
    opened then un-announced (auto_notify off): opens on an un-announced event count 0, not 1
    (which a naive count+clamp would wrongly report as 100%)."""
    events = FakeEventRepo(
        [
            # only e1 is announced; e2 is NOT (auto_notify off, no manual push).
            make_event(id="e1", school_id=_S1, notified_at=datetime(2026, 3, 1, tzinfo=UTC)),
            make_event(id="e2", school_id=_S1, auto_notify=False),
        ]
    )
    reads = FakeNotificationReadRepo()
    # The ONLY open is on the un-announced e2 — so reach against the announced set is 0.
    reads.set_seen("st1", "e2", datetime(2026, 3, 6, tzinfo=UTC))
    svc = _analytics(schools=FakeSchoolRepo([make_school(id=_S1)]), events=events, reads=reads)
    a = await svc.school_analytics(school_id=_S1)
    assert a.events_distributed == 1
    assert a.events_opened == 0  # e2's open doesn't count — e2 isn't announced


async def test_school_analytics_first_open_trend_can_decline() -> None:
    """The first-opens trend buckets the immutable created_at by month (decline-capable)."""
    reads = FakeNotificationReadRepo()
    # 2 first-opens in Feb, 1 in Mar — a month-over-month decline.
    reads.set_seen("st1", "e1", datetime(2026, 2, 1, tzinfo=UTC))
    reads.set_seen("st2", "e1", datetime(2026, 2, 2, tzinfo=UTC))
    reads.set_seen("st3", "e2", datetime(2026, 3, 1, tzinfo=UTC))
    svc = _analytics(schools=FakeSchoolRepo([make_school(id=_S1)]), reads=reads)
    a = await svc.school_analytics(school_id=_S1)
    by_month = {m.month: m.first_opens for m in a.months}
    assert by_month.get("2026-02") == 2
    assert by_month.get("2026-03") == 1


async def test_school_analytics_empty_school_reads_zero() -> None:
    """A school with no opens/saves/verdicts reads zero for every new metric (the real
    tenant-scoping of each aggregate is proven by the gated Postgres round-trips)."""
    svc = _analytics(schools=FakeSchoolRepo([make_school(id=_S1)]))
    a = await svc.school_analytics(school_id=_S1)
    assert a.events_opened == 0
    assert a.students_saved == 0
    assert a.quality == ()


# ======================================================================
# C · answers behind the numbers
# ======================================================================


async def test_never_signed_in_and_never_opened_filters() -> None:
    """The two activity filters exclude students who HAVE signed in / HAVE opened."""
    users = FakeUserRepo(
        [
            make_user(id="u1", school_id=_S1, role=Role.STUDENT, email="u1@x.io"),
            make_user(id="u2", school_id=_S1, role=Role.STUDENT, email="u2@x.io"),
        ]
    )
    students = FakeStudentRepo(
        [
            make_student(id="st1", school_id=_S1, user_id="u1"),
            make_student(id="st2", school_id=_S1, user_id="u2"),
        ]
    )
    reads = FakeNotificationReadRepo()
    students.link_login_activity(users.signed_in_of)
    students.link_opened(reads.has_opened)

    await users.touch_last_login("u1")  # u1 signed in
    reads.set_seen("st2", "e1", datetime(2026, 3, 1, tzinfo=UTC))  # st2 opened

    # never signed in → only st2 (u2 never logged in)
    ids = await students.list_ids(_S1, never_signed_in=True)
    assert ids == ["st2"]
    # never opened → only st1 (st2 has a read)
    ids2 = await students.list_ids(_S1, never_opened=True)
    assert ids2 == ["st1"]


def _engagement(
    *,
    students: FakeStudentRepo,
    reader: FakeMlResultsReader,
    corrections: FakeMatchCorrectionRepo,
    reads: FakeNotificationReadRepo,
    audit: FakeDownloadAuditRepo,
) -> EngagementService:
    return EngagementService(students, reader, corrections, reads, audit)


async def test_student_engagement_composition_and_404() -> None:
    students = FakeStudentRepo([make_student(id="st1", school_id=_S1, user_id="u1")])
    reader = FakeMlResultsReader(
        [
            make_appearance(student_id="st1", media_id="m1", event_id="e1"),
            make_appearance(student_id="st1", media_id="m2", event_id="e2"),
        ]
    )
    reads = FakeNotificationReadRepo()
    reads.set_seen("st1", "e1", datetime(2026, 3, 1, tzinfo=UTC))
    reads.set_seen("st1", "e2", datetime(2026, 3, 4, tzinfo=UTC))
    audit = FakeDownloadAuditRepo(
        [make_download_audit_entry(id="a1", school_id=_S1, subject_student_id="st1")]
    )
    svc = _engagement(
        students=students,
        reader=reader,
        corrections=FakeMatchCorrectionRepo(),
        reads=reads,
        audit=audit,
    )
    eng = await svc.student_engagement(school_id=_S1, student_id="st1")
    assert eng.events_appearing == 2
    assert eng.photos_appearing == 2
    assert eng.events_opened == 2
    assert eng.last_opened_at == datetime(2026, 3, 4, tzinfo=UTC)
    assert eng.downloads == 1

    # A foreign/unknown student is a 404 before any composition.
    with pytest.raises(NotFoundError):
        await svc.student_engagement(school_id=_S1, student_id="ghost")


async def test_roster_carries_first_seen_and_download_count() -> None:
    events = FakeEventRepo(
        [make_event(id="e1", school_id=_S1, completed_at=datetime(2026, 3, 1, tzinfo=UTC),
                    notified_at=datetime(2026, 3, 1, tzinfo=UTC))]
    )
    reader = FakeMlResultsReader(
        [make_appearance(student_id="st1", media_id="m1", event_id="e1")]
    )
    students = FakeStudentRepo(
        [make_student(id="st1", school_id=_S1, user_id="u1", name="Ann")]
    )
    reads = FakeNotificationReadRepo()
    reads.set_seen("st1", "e1", datetime(2026, 3, 2, tzinfo=UTC))  # opened after announce
    audit = FakeDownloadAuditRepo(
        [
            make_download_audit_entry(id="a1", school_id=_S1, event_id="e1",
                                      subject_student_id="st1"),
            make_download_audit_entry(id="a2", school_id=_S1, event_id="e1",
                                      subject_student_id="st1"),
        ]
    )
    svc = NotificationService(
        events, reader, students, reads, FakeNotificationChannel(),
        FakeMatchCorrectionRepo(), audit,
    )
    roster = await svc.event_roster(school_id=_S1, event_id="e1")
    entry = roster.entries[0]
    assert entry.student.id == "st1"
    assert entry.seen is True
    assert entry.first_seen_at == datetime(2026, 3, 2, tzinfo=UTC)
    assert entry.download_count == 2


async def test_roster_first_seen_persists_when_seen_resets_on_reannounce() -> None:
    """The two roster columns are the intended dual signal: a student who opened BEFORE a
    re-announce reads ``seen`` False (needs a nudge) yet keeps a persistent ``first_seen_at``."""
    # Re-announced 2026-03-10, but the student's only open was 2026-03-02 (before it).
    events = FakeEventRepo(
        [make_event(id="e1", school_id=_S1, completed_at=datetime(2026, 3, 1, tzinfo=UTC),
                    notified_at=datetime(2026, 3, 10, tzinfo=UTC))]
    )
    reader = FakeMlResultsReader(
        [make_appearance(student_id="st1", media_id="m1", event_id="e1")]
    )
    students = FakeStudentRepo([make_student(id="st1", school_id=_S1, user_id="u1")])
    reads = FakeNotificationReadRepo()
    reads.set_seen("st1", "e1", datetime(2026, 3, 2, tzinfo=UTC))  # opened before the re-announce
    svc = NotificationService(
        events, reader, students, reads, FakeNotificationChannel(),
        FakeMatchCorrectionRepo(), FakeDownloadAuditRepo(),
    )
    entry = (await svc.event_roster(school_id=_S1, event_id="e1")).entries[0]
    assert entry.seen is False  # opened before the last announce → needs a nudge
    assert entry.first_seen_at == datetime(2026, 3, 2, tzinfo=UTC)  # but the open persists


# ======================================================================
# D · estate age axis
# ======================================================================


async def test_estate_age_axis() -> None:
    born = datetime(2026, 1, 1, tzinfo=UTC)
    schools = FakeSchoolRepo(
        [
            make_school(id="active"),
            make_school(id="fresh"),  # no events → not_started
        ]
    )
    # `active` school: created 2026-01-01, first announced 2026-01-11 (10 days), last event
    # created 2026-02-01. `fresh` school has no events at all.
    events = FakeEventRepo(
        [
            make_event(
                id="e1", school_id="active",
                created_at=datetime(2026, 1, 5, tzinfo=UTC),
                notified_at=datetime(2026, 1, 11, tzinfo=UTC),
            ),
            make_event(
                id="e2", school_id="active",
                created_at=datetime(2026, 2, 1, tzinfo=UTC),
                notified_at=datetime(2026, 1, 20, tzinfo=UTC),
            ),
        ]
    )
    # make_school defaults created_at to _NOW (2026-01-01), so the day-delta is well-defined.
    svc = _analytics(schools=schools, events=events)
    estate = await svc.estate_analytics()
    by_id = {f.school_id: f for f in estate.schools}

    active = by_id["active"]
    assert active.not_started is False
    assert active.created_at == born
    # first announce = min(2026-01-11, 2026-01-20) = 2026-01-11 → 10 days from Jan 1
    assert active.days_to_first_delivery == 10
    # stalled_since = max event created_at = 2026-02-01
    assert active.stalled_since == datetime(2026, 2, 1, tzinfo=UTC)

    fresh = by_id["fresh"]
    assert fresh.not_started is True
    assert fresh.days_to_first_delivery is None
    assert fresh.stalled_since is None


# ======================================================================
# route smoke — perms + the new read shapes
# ======================================================================


def _u(*, id: str, role: Role, school_id: str | None, email: str) -> User:
    # Explicit annotation: _HASHER.hash returns Any (untyped passlib), so pin the type here.
    user: User = make_user(
        id=id, school_id=school_id, email=email,
        password_hash=_HASHER.hash("pw"), role=role,
    )
    return user


def _client() -> TestClient:
    container = SeededContainer(
        FakeUserRepo(
            [
                _u(id="sa", role=Role.SCHOOL_ADMIN, school_id=_S1, email="sa@x.io"),
                _u(id="stu", role=Role.STUDENT, school_id=_S1, email="stu@x.io"),
            ]
        ),
        FakeSchoolRepo([make_school(id=_S1)]),
        students=FakeStudentRepo(
            [make_student(id="st1", school_id=_S1, user_id="stu")]
        ),
        events=FakeEventRepo([make_event(id="e1", school_id=_S1, created_by="sa")]),
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


def test_event_detail_route_exposes_created_by_email() -> None:
    client = _client()
    resp = client.get("/v1/events/e1", headers=_auth(_token(client, "sa")))
    assert resp.status_code == 200, resp.text
    assert resp.json()["created_by_email"] == "sa@x.io"


def test_engagement_route_perms_and_shape() -> None:
    client = _client()
    resp = client.get(
        "/v1/students/st1/engagement", headers=_auth(_token(client, "sa"))
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {
        "events_appearing", "photos_appearing", "events_opened",
        "last_opened_at", "downloads",
    } <= set(body)

    # a student can't reach the staff engagement read; a foreign/unknown id 404s.
    assert (
        client.get("/v1/students/st1/engagement", headers=_auth(_token(client, "stu")))
    ).status_code == 403
    assert (
        client.get("/v1/students/ghost/engagement", headers=_auth(_token(client, "sa")))
    ).status_code == 404


def test_students_list_activity_filter_422_on_bad_value() -> None:
    client = _client()
    tok = _auth(_token(client, "sa"))
    assert client.get("/v1/students?login=never", headers=tok).status_code == 200
    assert client.get("/v1/students?opened=never", headers=tok).status_code == 200
    # an unknown activity-filter value 422s via the ActivityFilter enum.
    assert client.get("/v1/students?login=sometimes", headers=tok).status_code == 422
