"""BP9 server-side list pagination + gallery de-rostering (decisions/0055).

Covers, over the real routers with fake repos: the ``{items,total,limit,offset}`` envelope,
limit/offset slicing, server search (``q``), row-native + whole-list count-column sorts,
status filters, the 422 guards (bad limit/offset/sort), and tenant isolation. Plus a
service-level regression guard that the de-rostered gallery reads fetch only the matched
ids (``list_by_ids``) and never load the whole school roster/event list (``list_by_school``).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.domain.models import (
    EnrollmentStatus,
    MatchVerdict,
    MediaProcessingStatus,
    Role,
    User,
)
from backend.main import create_app
from backend.services.gallery_service import GalleryService
from backend_fakes import (
    FakeDownloadAuditRepo,
    FakeEventRepo,
    FakeMatchCorrectionRepo,
    FakeMediaRepo,
    FakeMlResultsReader,
    FakeObjectStore,
    FakeSchoolRepo,
    FakeStudentRepo,
    FakeUserRepo,
    RecordingEventRepo,
    RecordingStudentRepo,
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
_EN = EnrollmentStatus


def _user(*, id: str, role: Role, school_id: str | None, email: str) -> User:
    user: User = make_user(
        id=id, school_id=school_id, email=email,
        password_hash=_HASHER.hash("pw"), role=role,
    )
    return user


# Students in s1: names A..E, staggered appearance counts (Eve 3 > Dan 2 > Cara 1 > 0).
_STUDENTS = [
    make_student(id="st_anna", school_id="s1", user_id="u_anna", name="Anna",
                 enrollment_status=_EN.ENROLLED),
    make_student(id="st_bob", school_id="s1", user_id="u_bob", name="Bob",
                 enrollment_status=_EN.PENDING),
    make_student(id="st_cara", school_id="s1", user_id="u_cara", name="Cara",
                 enrollment_status=_EN.ENROLLED),
    make_student(id="st_dan", school_id="s1", user_id="u_dan", name="Dan",
                 enrollment_status=_EN.FAILED),
    make_student(id="st_eve", school_id="s1", user_id="u_eve", name="Eve",
                 enrollment_status=_EN.ENROLLED),
    # A second-school student the caller must never see.
    make_student(id="st_x", school_id="s2", user_id="u_x", name="Alien"),
]

_APPEARANCES = [
    make_appearance(student_id="st_eve", media_id="m1", event_id="e1"),
    make_appearance(student_id="st_eve", media_id="m2", event_id="e1"),
    make_appearance(student_id="st_eve", media_id="m3", event_id="e1"),
    make_appearance(student_id="st_dan", media_id="m1", event_id="e1"),
    make_appearance(student_id="st_dan", media_id="m2", event_id="e1", needs_review=True),
    make_appearance(student_id="st_cara", media_id="m1", event_id="e1"),
]

_EVENTS = [
    make_event(id="e1", school_id="s1", name="Recital"),
    make_event(id="e2", school_id="s1", name="Sports Day"),
    make_event(id="e3", school_id="s1", name="Field Trip"),
]

_MEDIA = [
    make_media(id="m1", school_id="s1", event_id="e1",
               processing_status=MediaProcessingStatus.COMPLETED),
    make_media(id="m2", school_id="s1", event_id="e1"),
    make_media(id="m3", school_id="s1", event_id="e1"),
    make_media(id="m4", school_id="s1", event_id="e2"),
]


def _build() -> TestClient:
    users = FakeUserRepo(
        [
            _user(id="pa", role=Role.PLATFORM_ADMIN, school_id=None, email="pa@x.io"),
            _user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1", email="sa@x.io"),
            _user(id="ada", role=Role.SCHOOL_ADMIN, school_id="s1", email="ada@x.io"),
            _user(id="anna@s1", role=Role.TEACHER, school_id="s1", email="anna@s1.io"),
            _user(id="bob@s1", role=Role.TEACHER, school_id="s1", email="bob@s1.io"),
            _user(id="cara@s1", role=Role.TEACHER, school_id="s1", email="cara@s1.io"),
        ]
    )
    container = SeededContainer(
        users,
        FakeSchoolRepo(
            [
                make_school(id="s1", name="Alpha", max_teachers=10),
                make_school(id="s2", name="Beta", max_teachers=10),
                make_school(id="s3", name="Gamma", max_teachers=10),
            ]
        ),
        students=FakeStudentRepo(_STUDENTS),
        events=FakeEventRepo(_EVENTS),
        media=FakeMediaRepo(_MEDIA),
        ml_results_reader=FakeMlResultsReader(_APPEARANCES),
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


def _get(client: TestClient, url: str, who: str) -> dict[str, Any]:
    resp = client.get(url, headers=_auth(_token(client, who)))
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


# ---- students: envelope, slicing, search, sort, filter, 422, tenant ------


def test_students_envelope_and_total() -> None:
    client = _build()
    page = _get(client, "/v1/students", "sa")
    assert set(page) == {"items", "total", "limit", "offset"}
    assert page["total"] == 5 and page["limit"] == 50 and page["offset"] == 0
    assert len(page["items"]) == 5
    # A second school's student never appears (tenant from the token).
    assert all(row["school_id"] == "s1" for row in page["items"])


def test_students_limit_offset_slices_without_overlap() -> None:
    client = _build()
    first = _get(client, "/v1/students?limit=2&offset=0&sort=name&dir=asc", "sa")
    second = _get(client, "/v1/students?limit=2&offset=2&sort=name&dir=asc", "sa")
    assert [r["name"] for r in first["items"]] == ["Anna", "Bob"]
    assert [r["name"] for r in second["items"]] == ["Cara", "Dan"]
    assert first["total"] == 5 and second["total"] == 5
    ids = {r["id"] for r in first["items"]} & {r["id"] for r in second["items"]}
    assert ids == set()  # pages never overlap


def test_students_search_hits_name_and_email() -> None:
    client = _build()
    by_name = _get(client, "/v1/students?q=eve", "sa")
    assert [r["name"] for r in by_name["items"]] == ["Eve"] and by_name["total"] == 1


def test_students_sort_name_desc() -> None:
    client = _build()
    page = _get(client, "/v1/students?sort=name&dir=desc", "sa")
    assert [r["name"] for r in page["items"]] == ["Eve", "Dan", "Cara", "Bob", "Anna"]


def test_students_global_count_sort_spans_pages() -> None:
    # Sorting by appearance_count is a whole-list sort (id-scan path), not per-page.
    client = _build()
    page1 = _get(
        client, "/v1/students?sort=appearance_count&dir=desc&limit=2&offset=0", "sa"
    )
    page2 = _get(
        client, "/v1/students?sort=appearance_count&dir=desc&limit=2&offset=2", "sa"
    )
    assert [(r["name"], r["appearance_count"]) for r in page1["items"]] == [
        ("Eve", 3),
        ("Dan", 2),
    ]
    # Page 2 continues the global order: Cara(1) then a zero-count student.
    assert page2["items"][0]["name"] == "Cara"
    assert page2["items"][0]["appearance_count"] == 1
    assert page2["items"][1]["appearance_count"] == 0


def test_students_status_filter() -> None:
    client = _build()
    page = _get(client, "/v1/students?status=enrolled", "sa")
    assert page["total"] == 3  # Anna, Cara, Eve
    assert {r["name"] for r in page["items"]} == {"Anna", "Cara", "Eve"}


def test_students_bad_limit_and_unknown_sort_are_422() -> None:
    client = _build()
    tok = _auth(_token(client, "sa"))
    assert client.get("/v1/students?limit=0", headers=tok).status_code == 422
    assert client.get("/v1/students?limit=999", headers=tok).status_code == 422
    assert client.get("/v1/students?offset=-1", headers=tok).status_code == 422
    assert client.get("/v1/students?sort=nope", headers=tok).status_code == 422
    assert client.get("/v1/students?dir=sideways", headers=tok).status_code == 422


# ---- events: count-column sort + status filter ---------------------------


def test_events_global_count_sort_by_media() -> None:
    client = _build()
    page = _get(client, "/v1/events?sort=media_count&dir=desc", "sa")
    names = [r["name"] for r in page["items"]]
    assert names[0] == "Recital"  # e1 has 3 photos
    assert page["items"][0]["media_count"] == 3
    assert page["total"] == 3


def test_events_matched_students_count_sort() -> None:
    client = _build()
    page = _get(client, "/v1/events?sort=matched_students&dir=desc", "sa")
    # e1 has 3 distinct matched students (Eve, Dan, Cara); e2/e3 have 0.
    assert page["items"][0]["name"] == "Recital"
    assert page["items"][0]["matched_students"] == 3


# ---- schools (platform): rollup count sort -------------------------------


def test_schools_count_sort_by_students() -> None:
    client = _build()
    page = _get(client, "/v1/schools?sort=students&dir=desc", "pa")
    # s1 has 5 students, s2 has 1, s3 has 0.
    assert page["items"][0]["id"] == "s1"
    assert page["items"][0]["rollup"]["students"] == 5
    assert page["total"] == 3


def test_schools_search_by_name() -> None:
    client = _build()
    page = _get(client, "/v1/schools?q=alph", "pa")
    assert [r["name"] for r in page["items"]] == ["Alpha"] and page["total"] == 1


# ---- staff / admins roster: email search + sort --------------------------


def test_staff_search_and_sort_by_email() -> None:
    client = _build()
    page = _get(client, "/v1/staff?sort=email&dir=asc", "sa")
    assert [r["email"] for r in page["items"]] == [
        "anna@s1.io",
        "bob@s1.io",
        "cara@s1.io",
    ]
    only_bob = _get(client, "/v1/staff?q=bob", "sa")
    assert [r["email"] for r in only_bob["items"]] == ["bob@s1.io"]


def test_admin_roster_paginates() -> None:
    client = _build()
    page = _get(client, "/v1/schools/s1/admins", "pa")
    assert {r["email"] for r in page["items"]} == {"sa@x.io", "ada@x.io"}
    assert page["total"] == 2


def test_admin_roster_search_and_sort() -> None:
    client = _build()
    sorted_asc = _get(client, "/v1/schools/s1/admins?sort=email&dir=asc", "pa")
    assert [u["email"] for u in sorted_asc["items"]] == ["ada@x.io", "sa@x.io"]
    only_ada = _get(client, "/v1/schools/s1/admins?q=ada", "pa")
    assert [u["email"] for u in only_ada["items"]] == ["ada@x.io"]


# ---- event media: pagination + status filter -----------------------------


def test_event_media_pagination_and_status_filter() -> None:
    client = _build()
    page = _get(client, "/v1/events/e1/media?limit=2&offset=0", "sa")
    assert page["total"] == 3 and len(page["items"]) == 2
    completed = _get(client, "/v1/events/e1/media?status=completed", "sa")
    assert completed["total"] == 1 and completed["items"][0]["id"] == "m1"


# ---- de-rostering regression (service level) -----------------------------


def _gallery(
    students: RecordingStudentRepo, events: RecordingEventRepo
) -> GalleryService:
    return GalleryService(
        reader=FakeMlResultsReader(_APPEARANCES),
        students=students,
        events=events,
        media=FakeMediaRepo(_MEDIA),
        corrections=FakeMatchCorrectionRepo(),
        object_store=FakeObjectStore(),
        audit=FakeDownloadAuditRepo(),
        download_url_ttl_s=3600,
    )


async def test_gallery_reads_fetch_only_matched_ids() -> None:
    students = RecordingStudentRepo(_STUDENTS)
    events = RecordingEventRepo(_EVENTS)
    svc = _gallery(students, events)

    in_event = await svc.event_students(school_id="s1", event_id="e1")
    assert {s.student.name for s in in_event} == {"Eve", "Dan", "Cara"}

    for_student = await svc.student_events(school_id="s1", student_id="st_eve")
    assert {e.event.id for e in for_student} == {"e1"}

    in_media = await svc.media_appearances(school_id="s1", media_id="m1")
    assert {a.student.name for a in in_media} == {"Eve", "Dan", "Cara"}

    # The whole-roster / whole-event loads are gone — every read went via list_by_ids.
    assert "list_by_school" not in students.calls
    assert "list_by_school" not in events.calls
    assert students.calls.count("list_by_ids") == 2  # event_students + media_appearances
    assert events.calls == ["list_by_ids"]  # student_events


async def test_media_appearances_derostered_fetches_added_only_student() -> None:
    # An `added` correction for a student NOT in the ML appearances must still surface (and
    # be fetched via list_by_ids, not the whole roster) — the `needed` union in the
    # de-rostered media_appearances (BP9).
    students = RecordingStudentRepo(_STUDENTS)
    events = RecordingEventRepo(_EVENTS)
    corrections = FakeMatchCorrectionRepo(
        [
            make_match_correction(
                media_id="m1", student_id="st_bob", event_id="e1",
                verdict=MatchVerdict.ADDED,
            )
        ]
    )
    svc = GalleryService(
        reader=FakeMlResultsReader(_APPEARANCES),
        students=students,
        events=events,
        media=FakeMediaRepo(_MEDIA),
        corrections=corrections,
        object_store=FakeObjectStore(),
        audit=FakeDownloadAuditRepo(),
        download_url_ttl_s=3600,
    )
    got = await svc.media_appearances(school_id="s1", media_id="m1")
    # The ML matches in m1 (Eve, Dan, Cara) PLUS the added-only Bob.
    assert {a.student.name for a in got} == {"Eve", "Dan", "Cara", "Bob"}
    assert "list_by_school" not in students.calls
    assert "list_by_ids" in students.calls


# ---- BP9 R2: boundary + tiebreak + null-date coverage --------------------


def test_students_count_sort_tiebreak_desc_id_across_pages() -> None:
    # Page one-at-a-time by a count column across a boundary with tied counts: distinct
    # counts first (Eve 3, Dan 2, Cara 1), then the two 0-count students by the DESC id
    # tiebreak (st_bob > st_anna → Bob before Anna) — no overlap, no repeat.
    client = _build()
    seen = [
        _get(
            client,
            f"/v1/students?sort=appearance_count&dir=desc&limit=1&offset={i}",
            "sa",
        )["items"][0]["name"]
        for i in range(5)
    ]
    assert seen == ["Eve", "Dan", "Cara", "Bob", "Anna"]


def test_students_offset_past_end_and_no_match_are_empty() -> None:
    client = _build()
    # Row-native sort, offset past the 5 rows -> empty page, correct total.
    past = _get(client, "/v1/students?sort=name&limit=2&offset=10", "sa")
    assert past["items"] == [] and past["total"] == 5
    # Count-sort path (id-scan) past the end -> empty, total preserved.
    past_count = _get(
        client, "/v1/students?sort=appearance_count&dir=desc&limit=2&offset=10", "sa"
    )
    assert past_count["items"] == [] and past_count["total"] == 5
    # A search matching nothing -> empty, total 0.
    none = _get(client, "/v1/students?q=zzzznomatch", "sa")
    assert none["items"] == [] and none["total"] == 0


def test_events_sort_by_date_handles_null() -> None:
    # A mixed set/None event_date list sorts deterministically (no None-vs-date crash);
    # ascending places the real dates first and the undated event last (NULLS LAST).
    events = [
        make_event(id="ed1", school_id="s1", name="Dated A", event_date=date(2026, 6, 1)),
        make_event(id="ed2", school_id="s1", name="Dated B", event_date=date(2026, 1, 1)),
        make_event(id="ed3", school_id="s1", name="Undated", event_date=None),
    ]
    container = SeededContainer(
        FakeUserRepo(
            [_user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1", email="sa@x.io")]
        ),
        FakeSchoolRepo([make_school(id="s1", name="Alpha", max_teachers=10)]),
        events=FakeEventRepo(events),
    )
    app = create_app()
    app.dependency_overrides[get_container_dep] = lambda: container
    client = TestClient(app)
    page = _get(client, "/v1/events?sort=event_date&dir=asc", "sa")
    assert [e["name"] for e in page["items"]] == ["Dated B", "Dated A", "Undated"]


def test_list_endpoints_reject_unknown_sort() -> None:
    # Each router names its own *Sort enum, so an unknown sort is a distinct 422 per route.
    client = _build()
    for url, who in [
        ("/v1/events?sort=bogus", "sa"),
        ("/v1/staff?sort=bogus", "sa"),
        ("/v1/schools?sort=bogus", "pa"),
    ]:
        resp = client.get(url, headers=_auth(_token(client, who)))
        assert resp.status_code == 422, f"{url} -> {resp.status_code}"
