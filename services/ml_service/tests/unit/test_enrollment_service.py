"""EnrollmentService behaviour: per-photo isolation, pick-largest, replace."""

import pytest
from fakes import (
    StubDetectionRepository,
    StubDetector,
    StubEmbedder,
    StubMatchRepository,
    StubMediaStore,
    StubReferencePhotoRepository,
    StubVectorIndex,
    box,
    normalized,
)
from ml_service.domain.errors import EnrollmentError
from ml_service.domain.models import EMBEDDING_DIM, SIMILARITY_METRIC, PhotoStatus
from ml_service.orchestration.enrollment import EnrollmentService


def _svc(
    ref: object = None,
    media: object = None,
    detector: object = None,
    embedder: object = None,
    index: object = None,
    *,
    matches: object = None,
    detections: object = None,
) -> EnrollmentService:
    """Build an EnrollmentService, defaulting each port to its stub (BP8e added the
    matches + detections ports, used only by delete())."""
    return EnrollmentService(
        ref or StubReferencePhotoRepository(),  # type: ignore[arg-type]
        media or StubMediaStore(),  # type: ignore[arg-type]
        detector or StubDetector(),  # type: ignore[arg-type]
        embedder or StubEmbedder(),  # type: ignore[arg-type]
        index or StubVectorIndex(),  # type: ignore[arg-type]
        matches or StubMatchRepository(),  # type: ignore[arg-type]
        detections or StubDetectionRepository(),  # type: ignore[arg-type]
    )


async def test_single_photo_enrolled_with_meta() -> None:
    media = StubMediaStore({"u1": b"img1"})
    detector = StubDetector(mapping={b"img1": [box()]})
    embedder = StubEmbedder(version="emb-9")
    index = StubVectorIndex()
    svc = _svc(StubReferencePhotoRepository(), media, detector, embedder, index)

    result = await svc.enroll("sch1", "stu1", ["u1"])

    assert result.embeddings_stored == 1
    assert (result.school_id, result.student_id) == ("sch1", "stu1")
    assert [p.status for p in result.photo_results] == [PhotoStatus.ENROLLED]
    assert len(index.upserts) == 1
    school, student, embs, meta = index.upserts[0]
    assert (school, student) == ("sch1", "stu1")
    assert len(embs) == 1
    assert meta["embedding_model_version"] == "emb-9"
    assert meta["dim"] == EMBEDDING_DIM
    assert meta["metric"] == SIMILARITY_METRIC


async def test_no_face_yields_no_upsert() -> None:
    media = StubMediaStore({"u1": b"img1"})
    detector = StubDetector(mapping={b"img1": []})
    index = StubVectorIndex()
    svc = _svc(
        StubReferencePhotoRepository(), media, detector, StubEmbedder(), index
    )

    result = await svc.enroll("s", "st", ["u1"])

    assert result.embeddings_stored == 0
    assert result.photo_results[0].status == PhotoStatus.NO_FACE
    assert index.upserts == []


async def test_multiple_faces_picks_largest() -> None:
    media = StubMediaStore({"u1": b"img1"})
    small, large = box(size=10.0), box(size=200.0)
    detector = StubDetector(mapping={b"img1": [small, large]})
    embedder = StubEmbedder()
    index = StubVectorIndex()
    svc = _svc(StubReferencePhotoRepository(), media, detector, embedder, index)

    result = await svc.enroll("s", "st", ["u1"])

    assert result.photo_results[0].status == PhotoStatus.MULTIPLE_FACES
    assert result.embeddings_stored == 1
    assert embedder.calls[0][1] is large  # embedded the largest box


async def test_mixed_outcomes_do_not_abort_each_other() -> None:
    media = StubMediaStore({"u_ok1": b"a", "u_noface": b"b", "u_ok2": b"d"})  # u_err missing
    detector = StubDetector(mapping={b"a": [box()], b"b": [], b"d": [box()]})
    index = StubVectorIndex()
    svc = _svc(
        StubReferencePhotoRepository(), media, detector, StubEmbedder(), index
    )

    result = await svc.enroll("s", "st", ["u_ok1", "u_noface", "u_err", "u_ok2"])

    assert [p.status for p in result.photo_results] == [
        PhotoStatus.ENROLLED,
        PhotoStatus.NO_FACE,
        PhotoStatus.ERROR,
        PhotoStatus.ENROLLED,
    ]
    assert result.photo_results[2].detail is not None  # ERROR carries the cause
    assert result.embeddings_stored == 2
    assert len(index.upserts) == 1
    assert len(index.upserts[0][2]) == 2


async def test_all_failures_never_wipe_prior_embeddings() -> None:
    media = StubMediaStore({})  # every fetch raises
    index = StubVectorIndex()
    svc = _svc(
        StubReferencePhotoRepository(), media, StubDetector(), StubEmbedder(), index
    )

    result = await svc.enroll("s", "st", ["x", "y"])

    assert result.embeddings_stored == 0
    assert all(p.status == PhotoStatus.ERROR for p in result.photo_results)
    assert index.upserts == []  # no upsert -> existing index untouched


async def test_embedder_failure_is_isolated() -> None:
    media = StubMediaStore({"u1": b"a", "u2": b"c"})
    detector = StubDetector(mapping={b"a": [box()], b"c": [box()]})
    embedder = StubEmbedder(raise_for={b"a"})
    index = StubVectorIndex()
    svc = _svc(StubReferencePhotoRepository(), media, detector, embedder, index)

    result = await svc.enroll("s", "st", ["u1", "u2"])

    assert [p.status for p in result.photo_results] == [PhotoStatus.ERROR, PhotoStatus.ENROLLED]
    assert result.embeddings_stored == 1


async def test_reenroll_replaces_not_appends() -> None:
    media = StubMediaStore({"u1": b"a", "u2": b"c", "u3": b"d"})
    detector = StubDetector(mapping={b"a": [box()], b"c": [box()], b"d": [box()]})
    index = StubVectorIndex()
    ref = StubReferencePhotoRepository()
    svc = _svc(ref, media, detector, StubEmbedder(), index)

    await svc.enroll("s", "st", ["u1", "u2"])  # two embeddings
    await svc.enroll("s", "st", ["u3"])  # replace with one

    assert len(index.store[("s", "st")]) == 1
    assert await ref.get("s", "st") == ["u3"]


async def test_refresh_without_uris_uses_stored() -> None:
    media = StubMediaStore({"u1": b"a"})
    detector = StubDetector(mapping={b"a": [box()]})
    ref = StubReferencePhotoRepository()
    await ref.replace("s", "st", ["u1"])
    index = StubVectorIndex()
    svc = _svc(ref, media, detector, StubEmbedder(), index)

    result = await svc.enroll("s", "st")  # no photo_uris -> refresh from table

    assert result.embeddings_stored == 1


async def test_refresh_with_no_stored_uris_is_noop() -> None:
    ref = StubReferencePhotoRepository()  # nothing stored for the student
    index = StubVectorIndex()
    svc = _svc(ref, StubMediaStore(), StubDetector(), StubEmbedder(), index)

    result = await svc.enroll("s", "st")  # refresh against an empty table

    assert result.embeddings_stored == 0
    assert result.photo_results == ()
    assert index.upserts == []  # nothing to embed -> no upsert


async def test_delete_erases_all_ml_footprint() -> None:
    # BP8e: delete purges embeddings + reference-photo URIs + matches + detection candidates.
    ref = StubReferencePhotoRepository()
    await ref.replace("s", "st", ["u1"])
    index = StubVectorIndex()
    await index.upsert("s", "st", [normalized([1.0])], {})
    matches = StubMatchRepository()
    detections = StubDetectionRepository()
    svc = _svc(ref, index=index, matches=matches, detections=detections)

    await svc.delete("s", "st")

    assert index.deletes == [("s", "st")]
    assert await ref.get("s", "st") == []
    assert matches.deleted_students == [("s", "st")]
    assert detections.deleted_students == [("s", "st")]


async def test_empty_photo_uris_rejected_without_side_effects() -> None:
    ref = StubReferencePhotoRepository()
    await ref.replace("s", "st", ["keep1", "keep2"])  # pre-existing enrollment
    index = StubVectorIndex()
    svc = _svc(ref, StubMediaStore(), StubDetector(), StubEmbedder(), index)

    with pytest.raises(EnrollmentError):
        await svc.enroll("s", "st", [])

    assert await ref.get("s", "st") == ["keep1", "keep2"]  # stored URIs untouched
    assert index.upserts == []  # no upsert


async def test_duplicate_uris_are_deduped() -> None:
    media = StubMediaStore({"u1": b"a"})
    detector = StubDetector(mapping={b"a": [box()]})
    index = StubVectorIndex()
    svc = _svc(
        StubReferencePhotoRepository(), media, detector, StubEmbedder(), index
    )

    result = await svc.enroll("s", "st", ["u1", "u1"])  # same photo twice

    assert result.embeddings_stored == 1  # deduped -> embedded once
    assert len(index.upserts[0][2]) == 1
