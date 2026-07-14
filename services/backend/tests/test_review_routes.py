"""End-to-end match-review routes (BP5, decisions/0042).

Staff confirm/reject/add/undo + the review lane, gated on match:review; and the overlay
they drive (a rejected match vanishes from the staff photo detail; an added student shows).
"""

from __future__ import annotations

from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.domain.models import Role, User
from backend.main import create_app
from backend_fakes import (
    FakeEventRepo,
    FakeMediaRepo,
    FakeMlResultsReader,
    FakeSchoolRepo,
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

_HASHER = Argon2PasswordHasher()


def _user(*, id: str, role: Role, school_id: str | None, email: str) -> User:
    user: User = make_user(
        id=id, school_id=school_id, email=email,
        password_hash=_HASHER.hash("pw"), role=role,
    )
    return user


def _build() -> TestClient:
    """School s1: an admin + a student login (stu→st1) + a roster student st2; event e1 with
    photo m1 where st1 is an ambiguous (needs_review) ML match."""
    container = SeededContainer(
        FakeUserRepo(
            [
                _user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1", email="sa@x.io"),
                _user(id="stu", role=Role.STUDENT, school_id="s1", email="stu@x.io"),
            ]
        ),
        FakeSchoolRepo([make_school(id="s1")]),
        students=FakeStudentRepo(
            [
                make_student(id="st1", school_id="s1", user_id="stu", name="Bart"),
                make_student(id="st2", school_id="s1", user_id="stu2", name="Lisa"),
            ]
        ),
        events=FakeEventRepo([make_event(id="e1", school_id="s1")]),
        media=FakeMediaRepo([make_media(id="m1", school_id="s1", event_id="e1")]),
        ml_results_reader=FakeMlResultsReader(
            [make_appearance(student_id="st1", media_id="m1", event_id="e1", needs_review=True)]
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


def _appearance_ids(
    client: TestClient, sa: dict[str, str]
) -> dict[str, dict[str, object]]:
    resp = client.get("/v1/media/m1/appearances", headers=sa)
    assert resp.status_code == 200, resp.text
    return {a["student_id"]: a for a in resp.json()}


def test_review_lane_lists_ambiguous_then_clears_on_reject() -> None:
    client = _build()
    sa = _auth(_token(client, "sa"))

    lane = client.get("/v1/events/e1/review", headers=sa)
    assert lane.status_code == 200, lane.text
    assert [m["media_id"] for m in lane.json()] == ["m1"]

    # Reject st1 in m1.
    r = client.post("/v1/media/m1/appearances/st1", headers=sa, json={"verdict": "rejected"})
    assert r.status_code == 204, r.text

    # The lane is now empty (resolved); the staff detail still shows st1 as rejected.
    assert client.get("/v1/events/e1/review", headers=sa).json() == []
    assert _appearance_ids(client, sa)["st1"]["verdict"] == "rejected"


def test_confirm_marks_verdict_on_photo_detail() -> None:
    client = _build()
    sa = _auth(_token(client, "sa"))
    r = client.post("/v1/media/m1/appearances/st1", headers=sa, json={"verdict": "confirmed"})
    assert r.status_code == 204, r.text
    apps = _appearance_ids(client, sa)
    assert apps["st1"]["verdict"] == "confirmed"


def test_report_a_miss_adds_a_student() -> None:
    client = _build()
    sa = _auth(_token(client, "sa"))
    r = client.post("/v1/media/m1/appearances", headers=sa, json={"student_id": "st2"})
    assert r.status_code == 204, r.text
    apps = _appearance_ids(client, sa)
    assert apps["st2"]["verdict"] == "added"
    assert apps["st2"]["confidence"] is None  # no ML score for an added student


def test_undo_reverts_to_ml_truth() -> None:
    client = _build()
    sa = _auth(_token(client, "sa"))
    client.post("/v1/media/m1/appearances/st1", headers=sa, json={"verdict": "rejected"})
    assert _appearance_ids(client, sa)["st1"]["verdict"] == "rejected"
    undo = client.delete("/v1/media/m1/appearances/st1", headers=sa)
    assert undo.status_code == 204, undo.text
    assert _appearance_ids(client, sa)["st1"]["verdict"] is None  # back to raw ML match


def test_review_is_staff_only() -> None:
    client = _build()
    stu = _auth(_token(client, "stu"))
    assert client.get("/v1/events/e1/review", headers=stu).status_code == 403
    resp = client.post(
        "/v1/media/m1/appearances/st1", headers=stu, json={"verdict": "rejected"}
    )
    assert resp.status_code == 403
    assert client.post("/v1/media/m1/appearances/st1").status_code == 401


def test_verdict_rejects_bad_value() -> None:
    client = _build()
    sa = _auth(_token(client, "sa"))
    # 'added' is not a valid confirm/reject verdict (that's the report-a-miss route).
    resp = client.post("/v1/media/m1/appearances/st1", headers=sa, json={"verdict": "added"})
    assert resp.status_code == 422
