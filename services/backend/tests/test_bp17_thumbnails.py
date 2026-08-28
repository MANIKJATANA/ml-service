"""BP17 image thumbnails — backend-generated thumbnails + the two surfaces (decisions/0056).

At upload the frontend PUTs only the original; on register/create the **backend** downloads it,
compresses it (Pillow behind the ``Thumbnailer`` port), uploads a ``thumb-{name}.jpg`` sibling
under the same prefix, and stores the path. These tests cover: the backend generation on register
(image → a stored thumb under the prefix; video → none; a failed compress / a store outage → none,
best-effort); the stored-path serve policy in ``GalleryService.download_url`` +
``StudentService.reference_photo_url`` (thumb serves the stored sibling when present, else falls
back to full-res — pre-BP17 rows + video); the reference-photo endpoint's entitlement + 404s; and
the ``?size=`` param on the media download route. The ``FakeObjectStore`` records signed paths +
written objects; the ``FakeThumbnailer`` returns fixed bytes (or ``None``). The ML pipeline always
reads the full-res path, so nothing here touches enrollment/inference.
"""

from __future__ import annotations

import pytest
from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.domain.errors import NotFoundError
from backend.domain.models import (
    Media,
    MediaType,
    Role,
    Student,
    User,
)
from backend.main import create_app
from backend.services.gallery_service import GalleryService
from backend.services.media_service import MediaService
from backend.services.student_service import StudentService
from backend.services.thumbnails import thumb_key
from backend_fakes import (
    FakeDownloadAuditRepo,
    FakeEventRepo,
    FakeMatchCorrectionRepo,
    FakeMediaRepo,
    FakeMlClient,
    FakeMlResultsReader,
    FakeObjectStore,
    FakeSchoolRepo,
    FakeStudentGroupRepo,
    FakeStudentRepo,
    FakeThumbnailer,
    FakeUserRepo,
    SeededContainer,
    make_event,
    make_media,
    make_school,
    make_student,
    make_user,
)
from fastapi.testclient import TestClient

_HASHER = Argon2PasswordHasher()


# ---- backend generation on register (MediaService) -----------------------


def _media_svc(store: FakeObjectStore, thumbnailer: FakeThumbnailer) -> MediaService:
    erepo = FakeEventRepo([make_event(id="e1", school_id="s1")])
    return MediaService(
        FakeMediaRepo([]), erepo, store, thumbnailer, event_media_prefix="events"
    )


async def test_register_image_generates_thumbnail_under_prefix() -> None:
    store = FakeObjectStore()
    svc = _media_svc(store, FakeThumbnailer())
    media = await svc.register_media(
        school_id="s1", event_id="e1",
        storage_path="events/s1/e1/photo", media_type=MediaType.IMAGE,
    )
    # The backend generated + stored a thumb-*.jpg sibling under the same event prefix.
    assert media.thumbnail_path == thumb_key("events/s1/e1/photo")
    assert media.thumbnail_path == "events/s1/e1/thumb-photo.jpg"
    assert media.thumbnail_path in store.uploaded


async def test_register_video_has_no_thumbnail() -> None:
    store = FakeObjectStore()
    svc = _media_svc(store, FakeThumbnailer())
    media = await svc.register_media(
        school_id="s1", event_id="e1",
        storage_path="events/s1/e1/clip", media_type=MediaType.VIDEO,
    )
    assert media.thumbnail_path is None
    assert store.uploaded == {}  # video keeps a browser poster — nothing generated


async def test_register_image_no_thumb_when_compression_fails() -> None:
    # Best-effort: the compressor returns None → the media is still registered, thumb null.
    store = FakeObjectStore()
    svc = _media_svc(store, FakeThumbnailer(produces=False))
    media = await svc.register_media(
        school_id="s1", event_id="e1",
        storage_path="events/s1/e1/photo", media_type=MediaType.IMAGE,
    )
    assert media.thumbnail_path is None
    assert store.uploaded == {}


async def test_register_image_no_thumb_when_store_download_fails() -> None:
    # Best-effort: a store outage while fetching the original doesn't fail the register.
    store = FakeObjectStore(fail_downloads=True)
    svc = _media_svc(store, FakeThumbnailer())
    media = await svc.register_media(
        school_id="s1", event_id="e1",
        storage_path="events/s1/e1/photo", media_type=MediaType.IMAGE,
    )
    assert media.thumbnail_path is None


# ---- serve: GalleryService.download_url ----------------------------------


def _gallery(store: FakeObjectStore, *, media: list[Media]) -> GalleryService:
    return GalleryService(
        FakeMlResultsReader(),
        FakeStudentRepo(),
        FakeEventRepo(),
        FakeMediaRepo(media),
        FakeMatchCorrectionRepo(),
        store,
        FakeDownloadAuditRepo(),
        download_url_ttl_s=3600,
    )


async def _download(svc: GalleryService, media_id: str, *, thumbnail: bool) -> str:
    signed = await svc.download_url(
        school_id="s1",
        media_id=media_id,
        restrict_to_student_id=None,  # staff — any in-school media
        thumbnail=thumbnail,
    )
    return signed.download_url


async def test_thumb_serves_stored_thumbnail_when_present() -> None:
    store = FakeObjectStore()
    img = make_media(
        id="m1", school_id="s1", event_id="e1",
        storage_path="events/s1/e1/m1", thumbnail_path="events/s1/e1/thumb-m1.jpg",
    )
    url = await _download(_gallery(store, media=[img]), "m1", thumbnail=True)
    assert store.last_download_path == "events/s1/e1/thumb-m1.jpg"
    assert "thumb-m1.jpg" in url


async def test_full_always_serves_the_original_even_with_a_thumb() -> None:
    store = FakeObjectStore()
    img = make_media(
        id="m1", school_id="s1", event_id="e1",
        storage_path="events/s1/e1/m1", thumbnail_path="events/s1/e1/thumb-m1.jpg",
    )
    svc = _gallery(store, media=[img])
    thumb = await _download(svc, "m1", thumbnail=True)
    full = await _download(svc, "m1", thumbnail=False)
    assert store.last_download_path == "events/s1/e1/m1"  # last call = full
    assert "thumb-" not in full and thumb != full


async def test_thumb_falls_back_to_full_when_no_thumbnail_stored() -> None:
    # A pre-BP17 image (thumbnail_path is None) has no sibling → serve full-res.
    store = FakeObjectStore()
    img = make_media(
        id="m1", school_id="s1", event_id="e1",
        storage_path="events/s1/e1/m1", thumbnail_path=None,
    )
    url = await _download(_gallery(store, media=[img]), "m1", thumbnail=True)
    assert store.last_download_path == "events/s1/e1/m1" and "thumb-" not in url


async def test_thumb_falls_back_to_full_for_video() -> None:
    store = FakeObjectStore()
    vid = make_media(
        id="v1", school_id="s1", event_id="e1", media_type=MediaType.VIDEO,
        storage_path="events/s1/e1/v1", thumbnail_path=None,
    )
    url = await _download(_gallery(store, media=[vid]), "v1", thumbnail=True)
    assert store.last_download_path == "events/s1/e1/v1" and "thumb-" not in url


# ---- serve: StudentService.reference_photo_url ---------------------------


def _student_svc(store: FakeObjectStore, *, students: list[Student]) -> StudentService:
    return StudentService(
        FakeStudentRepo(students),
        FakeUserRepo(),
        FakeSchoolRepo(),
        _HASHER,
        store,
        FakeMlClient(),
        FakeThumbnailer(),
        FakeStudentGroupRepo(),
        reference_photo_prefix="reference-photos",
        download_url_ttl_s=3600,
    )


async def test_reference_photo_thumb_serves_stored_sibling() -> None:
    store = FakeObjectStore()
    s = make_student(
        id="st1", school_id="s1",
        reference_photo_path="reference-photos/s1/p.jpg",
        reference_photo_thumbnail_path="reference-photos/s1/thumb-p.jpg",
    )
    svc = _student_svc(store, students=[s])
    signed = await svc.reference_photo_url(school_id="s1", student_id="st1")
    assert store.last_download_path == "reference-photos/s1/thumb-p.jpg"
    assert "thumb-p.jpg" in signed.download_url


async def test_reference_photo_full_serves_the_original() -> None:
    store = FakeObjectStore()
    s = make_student(
        id="st1", school_id="s1",
        reference_photo_path="reference-photos/s1/p.jpg",
        reference_photo_thumbnail_path="reference-photos/s1/thumb-p.jpg",
    )
    svc = _student_svc(store, students=[s])
    await svc.reference_photo_url(school_id="s1", student_id="st1", thumbnail=False)
    assert store.last_download_path == "reference-photos/s1/p.jpg"


async def test_reference_photo_thumb_falls_back_when_no_sibling() -> None:
    store = FakeObjectStore()
    s = make_student(
        id="st1", school_id="s1",
        reference_photo_path="reference-photos/s1/p.jpg",
        reference_photo_thumbnail_path=None,  # pre-BP17 / generation failed
    )
    svc = _student_svc(store, students=[s])
    await svc.reference_photo_url(school_id="s1", student_id="st1")
    assert store.last_download_path == "reference-photos/s1/p.jpg"


async def test_reference_photo_photoless_is_404() -> None:
    s = make_student(id="st1", school_id="s1", reference_photo_path=None)
    svc = _student_svc(FakeObjectStore(), students=[s])
    with pytest.raises(NotFoundError):
        await svc.reference_photo_url(school_id="s1", student_id="st1")


async def test_reference_photo_foreign_tenant_is_404() -> None:
    s = make_student(id="st1", school_id="s1", reference_photo_path="reference-photos/s1/p")
    svc = _student_svc(FakeObjectStore(), students=[s])
    with pytest.raises(NotFoundError):
        await svc.reference_photo_url(school_id="s2", student_id="st1")  # other school


# ---- route-level: reference-photo endpoint + the media ?size param -------


def _user(*, id: str, role: Role, school_id: str | None, email: str) -> User:
    user: User = make_user(
        id=id, school_id=school_id, email=email,
        password_hash=_HASHER.hash("pw"), role=role,
    )
    return user


def _client() -> TestClient:
    students = FakeStudentRepo(
        [
            make_student(
                id="st1", school_id="s1", user_id="u_st1", name="Enrolled",
                reference_photo_path="reference-photos/s1/p.jpg",
                reference_photo_thumbnail_path="reference-photos/s1/thumb-p.jpg",
            ),
            make_student(
                id="st2", school_id="s1", user_id="u_st2", name="Photoless",
                reference_photo_path=None,
            ),
            make_student(
                id="st3", school_id="s1", user_id="u_st3", name="No Thumb",
                reference_photo_path="reference-photos/s1/q.jpg",
                reference_photo_thumbnail_path=None,  # a photo, no stored thumbnail
            ),
        ]
    )
    container = SeededContainer(
        FakeUserRepo(
            [
                _user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1", email="sa@x.io"),
                _user(id="u_st1", role=Role.STUDENT, school_id="s1", email="stu@x.io"),
            ]
        ),
        FakeSchoolRepo([make_school(id="s1", name="Alpha", max_teachers=10)]),
        students=students,
        media=FakeMediaRepo(
            [
                make_media(
                    id="m1", school_id="s1", event_id="e1", media_type=MediaType.IMAGE,
                    storage_path="events/s1/e1/m1",
                    thumbnail_path="events/s1/e1/thumb-m1.jpg",
                ),
                make_media(
                    id="v1", school_id="s1", event_id="e1", media_type=MediaType.VIDEO,
                    storage_path="events/s1/e1/v1",
                    thumbnail_path=None,  # video keeps a browser poster (no stored thumb)
                ),
            ]
        ),
    )
    app = create_app()
    app.dependency_overrides[get_container_dep] = lambda: container
    return TestClient(app)


def _auth(client: TestClient, who: str) -> dict[str, str]:
    resp = client.post("/v1/auth/login", json={"email": f"{who}@x.io", "password": "pw"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_reference_photo_route_staff_gets_thumb_and_full() -> None:
    client = _client()
    hdr = _auth(client, "sa")
    thumb = client.get("/v1/students/st1/reference-photo", headers=hdr)  # default thumb
    assert thumb.status_code == 200 and "thumb-" in thumb.json()["download_url"]
    full = client.get("/v1/students/st1/reference-photo?size=full", headers=hdr)
    assert full.status_code == 200 and "thumb-" not in full.json()["download_url"]


def test_reference_photo_route_photoless_and_bad_size() -> None:
    client = _client()
    hdr = _auth(client, "sa")
    assert client.get("/v1/students/st2/reference-photo", headers=hdr).status_code == 404
    assert (
        client.get("/v1/students/st1/reference-photo?size=nope", headers=hdr).status_code
        == 422
    )


def test_reference_photo_route_thumb_falls_back_to_full_when_no_sibling() -> None:
    client = _client()
    hdr = _auth(client, "sa")
    # st3 has a photo but no stored thumbnail → the default ?size=thumb serves the full-res URL.
    resp = client.get("/v1/students/st3/reference-photo", headers=hdr)
    assert resp.status_code == 200 and "thumb-" not in resp.json()["download_url"]


def test_reference_photo_route_requires_student_manage() -> None:
    client = _client()
    # A student lacks `student:manage` -> 403 (not their endpoint).
    resp = client.get("/v1/students/st1/reference-photo", headers=_auth(client, "stu"))
    assert resp.status_code == 403


def test_media_download_size_thumb_vs_full() -> None:
    client = _client()
    hdr = _auth(client, "sa")
    thumb = client.get("/v1/media/m1/download?size=thumb", headers=hdr)
    assert thumb.status_code == 200 and "thumb-" in thumb.json()["download_url"]
    full = client.get("/v1/media/m1/download", headers=hdr)  # default full
    assert full.status_code == 200 and "thumb-" not in full.json()["download_url"]
    assert client.get("/v1/media/m1/download?size=nope", headers=hdr).status_code == 422


def test_media_download_thumb_falls_back_to_full_for_thumbless_video() -> None:
    client = _client()
    hdr = _auth(client, "sa")
    # v1 is a video with no stored thumbnail → ?size=thumb serves the full-res object.
    resp = client.get("/v1/media/v1/download?size=thumb", headers=hdr)
    assert resp.status_code == 200 and "thumb-" not in resp.json()["download_url"]


def test_student_thumb_download_of_unappeared_media_is_404() -> None:
    # A thumbnail is just a different stored path — the entitlement gate must fire regardless
    # of size. The student (u_st1) appears in no seeded media, so both 404 (size never widens
    # entitlement).
    client = _client()
    hdr = _auth(client, "stu")
    assert client.get("/v1/media/m1/download?size=thumb", headers=hdr).status_code == 404
    assert client.get("/v1/media/m1/download", headers=hdr).status_code == 404
