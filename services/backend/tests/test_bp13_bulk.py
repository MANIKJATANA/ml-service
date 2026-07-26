"""BP13 — bulk actions & batch review (decisions/0061).

The batch review lane (``ReviewService.set_verdicts_batch``) — apply many confirm/reject
verdicts at once, skipping a pair that isn't a real match in the event (tenant-safe), stamping
``resolves_review`` — and the bulk event archive/restore (``EventService.set_status_bulk``,
tenant-scoped). Then the routes end-to-end: the batch endpoint clears the lane + drives the same
BP5 effective gate (a batch-rejected photo hides from the student), the bulk-status endpoint
archives many + skips a foreign id, both permission-gated, tenant from the token.
"""

from __future__ import annotations

import pytest
from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.domain.errors import NotFoundError
from backend.domain.models import (
    Appearance,
    Event,
    EventStatus,
    MatchVerdict,
    Role,
    User,
)
from backend.main import create_app
from backend.services.event_service import EventService
from backend.services.review_service import BatchVerdict, ReviewService
from backend_fakes import (
    FakeEventCategoryRepo,
    FakeEventJobProducer,
    FakeEventRepo,
    FakeMatchCorrectionRepo,
    FakeMediaRepo,
    FakeMlResultsReader,
    FakeSchoolRepo,
    FakeStudentGroupRepo,
    FakeStudentRepo,
    FakeUserRepo,
    SeededContainer,
    make_appearance,
    make_event,
    make_media,
    make_school,
    make_student,
    make_user,
)
from fastapi.testclient import TestClient

_S1 = "s1"
_S2 = "s2"


# ---- batch review service ----------------------------------------------


def _review_svc(
    *, appearances: list[Appearance] | None = None
) -> tuple[ReviewService, FakeMatchCorrectionRepo]:
    corr = FakeMatchCorrectionRepo()
    svc = ReviewService(
        FakeMlResultsReader(appearances or []),
        corr,
        FakeMediaRepo(
            [
                make_media(id="m1", school_id=_S1, event_id="e1"),
                make_media(id="m2", school_id=_S1, event_id="e1"),
            ]
        ),
        FakeStudentRepo(
            [
                make_student(id="a", school_id=_S1, user_id="ua"),
                make_student(id="b", school_id=_S1, user_id="ub"),
            ]
        ),
        FakeEventRepo([make_event(id="e1", school_id=_S1)]),
    )
    return svc, corr


async def test_batch_applies_many_skips_non_event_pairs_and_stamps_resolves() -> None:
    svc, corr = _review_svc(
        appearances=[
            make_appearance(student_id="a", media_id="m1", event_id="e1", needs_review=True),
            make_appearance(student_id="b", media_id="m1", event_id="e1", needs_review=True),
            make_appearance(student_id="a", media_id="m2", event_id="e1", needs_review=False),
        ]
    )
    applied = await svc.set_verdicts_batch(
        school_id=_S1,
        event_id="e1",
        decisions=[
            BatchVerdict("m1", "a", MatchVerdict.CONFIRMED),
            BatchVerdict("m1", "b", MatchVerdict.REJECTED),
            BatchVerdict("m2", "a", MatchVerdict.CONFIRMED),  # a real (non-ambiguous) match
            BatchVerdict("m9", "z", MatchVerdict.REJECTED),  # not in the event -> skipped
        ],
        corrected_by="staff",
    )
    assert applied == 3  # the bogus (m9, z) pair skipped
    ca = await corr.get(_S1, "m1", "a")
    cb = await corr.get(_S1, "m1", "b")
    cm2 = await corr.get(_S1, "m2", "a")
    assert ca is not None and ca.verdict is MatchVerdict.CONFIRMED and ca.resolves_review is True
    assert cb is not None and cb.verdict is MatchVerdict.REJECTED and cb.resolves_review is True
    # m2's match wasn't ambiguous -> confirming it doesn't count as resolving a review.
    assert cm2 is not None and cm2.resolves_review is False
    assert await corr.get(_S1, "m9", "z") is None  # never written


async def test_batch_resolving_ambiguous_matches_feeds_the_dashboard_count() -> None:
    # Each resolved needs_review pair stamps resolves_review -> the dashboard's
    # "N to review" (count_needs_review - count_resolved) drops by that many.
    svc, corr = _review_svc(
        appearances=[
            make_appearance(student_id="a", media_id="m1", event_id="e1", needs_review=True),
            make_appearance(student_id="b", media_id="m1", event_id="e1", needs_review=True),
        ]
    )
    assert await corr.count_resolved(_S1) == 0
    await svc.set_verdicts_batch(
        school_id=_S1,
        event_id="e1",
        decisions=[
            BatchVerdict("m1", "a", MatchVerdict.CONFIRMED),
            BatchVerdict("m1", "b", MatchVerdict.REJECTED),
        ],
        corrected_by="staff",
    )
    assert await corr.count_resolved(_S1) == 2  # both ambiguous matches resolved


async def test_batch_on_a_foreign_event_is_404() -> None:
    svc, _ = _review_svc(
        appearances=[make_appearance(student_id="a", media_id="m1", event_id="e1")]
    )
    with pytest.raises(NotFoundError):
        await svc.set_verdicts_batch(
            school_id=_S2,  # e1 belongs to s1
            event_id="e1",
            decisions=[BatchVerdict("m1", "a", MatchVerdict.CONFIRMED)],
            corrected_by="staff",
        )


# ---- bulk event status service -----------------------------------------


def _event_svc(*, events: list[Event] | None = None) -> tuple[EventService, FakeEventRepo]:
    erepo = FakeEventRepo(events or [])
    svc = EventService(
        erepo,
        FakeMediaRepo(),
        FakeEventJobProducer(),
        FakeEventCategoryRepo(),
        FakeStudentGroupRepo(),
    )
    return svc, erepo


async def test_bulk_status_is_tenant_scoped() -> None:
    svc, erepo = _event_svc(
        events=[
            make_event(id="e1", school_id=_S1),
            make_event(id="e2", school_id=_S1),
            make_event(id="ef", school_id=_S2),  # foreign — never touched
        ]
    )
    updated = await svc.set_status_bulk(
        school_id=_S1, event_ids=["e1", "e2", "ef"], status=EventStatus.ARCHIVED
    )
    assert updated == 2  # ef skipped
    r1 = await erepo.get(_S1, "e1")
    r2 = await erepo.get(_S1, "e2")
    assert r1 is not None and r1.status is EventStatus.ARCHIVED
    assert r2 is not None and r2.status is EventStatus.ARCHIVED
    foreign = await erepo.get(_S2, "ef")
    assert foreign is not None and foreign.status is EventStatus.ACTIVE  # untouched


# ---- routes ------------------------------------------------------------

_HASHER = Argon2PasswordHasher()


def _user(*, id: str, role: Role, school_id: str | None, email: str) -> User:
    user: User = make_user(
        id=id, school_id=school_id, email=email,
        password_hash=_HASHER.hash("pw"), role=role,
    )
    return user


def _build() -> TestClient:
    """School s1: an admin + a student login (stu->st1); events e1..e3 (active); photos m1, m2 in
    e1 where st1 is an ambiguous (needs_review) match in both."""
    container = SeededContainer(
        FakeUserRepo(
            [
                _user(id="sa", role=Role.SCHOOL_ADMIN, school_id=_S1, email="sa@x.io"),
                _user(id="stu", role=Role.STUDENT, school_id=_S1, email="stu@x.io"),
            ]
        ),
        FakeSchoolRepo([make_school(id=_S1)]),
        students=FakeStudentRepo(
            [make_student(id="st1", school_id=_S1, user_id="stu", name="Bart")]
        ),
        events=FakeEventRepo(
            [
                make_event(id="e1", school_id=_S1),
                make_event(id="e2", school_id=_S1),
                make_event(id="e3", school_id=_S1),
            ]
        ),
        media=FakeMediaRepo(
            [
                make_media(id="m1", school_id=_S1, event_id="e1"),
                make_media(id="m2", school_id=_S1, event_id="e1"),
            ]
        ),
        ml_results_reader=FakeMlResultsReader(
            [
                make_appearance(student_id="st1", media_id="m1", event_id="e1", needs_review=True),
                make_appearance(student_id="st1", media_id="m2", event_id="e1", needs_review=True),
            ]
        ),
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


def test_batch_review_clears_the_lane_and_records_verdicts() -> None:
    client = _build()
    sa = _auth(_token(client, "sa"))
    # Both m1 and m2 are in the lane.
    lane = client.get("/v1/events/e1/review", headers=sa)
    assert {m["media_id"] for m in lane.json()} == {"m1", "m2"}

    resp = client.post(
        "/v1/events/e1/review/batch",
        headers=sa,
        json={
            "verdicts": [
                {"media_id": "m1", "student_id": "st1", "verdict": "confirmed"},
                {"media_id": "m2", "student_id": "st1", "verdict": "rejected"},
                {"media_id": "mX", "student_id": "st1", "verdict": "rejected"},  # skipped
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["applied"] == 2  # the bogus pair skipped

    assert client.get("/v1/events/e1/review", headers=sa).json() == []  # lane cleared
    detail = {a["student_id"]: a for a in client.get("/v1/media/m1/appearances", headers=sa).json()}
    assert detail["st1"]["verdict"] == "confirmed"


def test_batch_reject_hides_the_photo_from_the_student() -> None:
    # The batch reuses the same BP5 effective gate: a batch-rejected match hides the photo.
    client = _build()
    sa = _auth(_token(client, "sa"))
    client.post(
        "/v1/events/e1/review/batch",
        headers=sa,
        json={
            "verdicts": [
                {"media_id": "m1", "student_id": "st1", "verdict": "confirmed"},
                {"media_id": "m2", "student_id": "st1", "verdict": "rejected"},
            ]
        },
    )
    stu = _auth(_token(client, "stu"))
    mine = client.get("/v1/me/media", headers=stu)
    assert mine.status_code == 200, mine.text
    ids = {m["media_id"] for m in mine.json()}
    assert ids == {"m1"}  # m1 confirmed shows; m2 rejected is hidden


def test_batch_review_is_staff_only_and_validates() -> None:
    client = _build()
    stu = _auth(_token(client, "stu"))
    body = {"verdicts": [{"media_id": "m1", "student_id": "st1", "verdict": "confirmed"}]}
    assert client.post("/v1/events/e1/review/batch", headers=stu, json=body).status_code == 403
    assert client.post("/v1/events/e1/review/batch", json=body).status_code == 401
    sa = _auth(_token(client, "sa"))
    # empty verdicts -> 422; a bad verdict value -> 422.
    empty = client.post("/v1/events/e1/review/batch", headers=sa, json={"verdicts": []})
    assert empty.status_code == 422
    bad = client.post(
        "/v1/events/e1/review/batch",
        headers=sa,
        json={"verdicts": [{"media_id": "m1", "student_id": "st1", "verdict": "added"}]},
    )
    assert bad.status_code == 422


def test_bulk_archive_and_restore_via_route() -> None:
    client = _build()
    sa = _auth(_token(client, "sa"))
    archived = client.post(
        "/v1/events/bulk-status",
        headers=sa,
        json={"event_ids": ["e1", "e2", "ef"], "status": "archived"},  # ef unknown -> skipped
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["updated"] == 2
    assert client.get("/v1/events/e1", headers=sa).json()["status"] == "archived"
    assert client.get("/v1/events/e3", headers=sa).json()["status"] == "active"  # not selected

    restored = client.post(
        "/v1/events/bulk-status",
        headers=sa,
        json={"event_ids": ["e1"], "status": "active"},
    )
    assert restored.status_code == 200 and restored.json()["updated"] == 1
    assert client.get("/v1/events/e1", headers=sa).json()["status"] == "active"


def test_bulk_status_requires_event_manage_and_validates() -> None:
    client = _build()
    stu = _auth(_token(client, "stu"))  # a student lacks event:manage
    body = {"event_ids": ["e1"], "status": "archived"}
    assert client.post("/v1/events/bulk-status", headers=stu, json=body).status_code == 403
    assert client.post("/v1/events/bulk-status", json=body).status_code == 401
    sa = _auth(_token(client, "sa"))
    assert client.post(
        "/v1/events/bulk-status", headers=sa, json={"event_ids": [], "status": "archived"}
    ).status_code == 422
