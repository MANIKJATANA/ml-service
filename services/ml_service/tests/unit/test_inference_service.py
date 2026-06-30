"""InferenceService behaviour: decision, dedupe, versioning, isolation, idempotency."""

import pytest
from fakes import (
    StubDetector,
    StubEmbedder,
    StubFrameExtractor,
    StubMatchRepository,
    StubMediaStore,
    StubThresholdProvider,
    StubVectorIndex,
    box,
    normalized,
)
from ml_service.domain.errors import ConfigurationError, MediaFetchError
from ml_service.domain.models import Candidate, Frame, InferenceJob, MediaType
from ml_service.orchestration.inference import InferenceService


def make_service(
    index: StubVectorIndex,
    *,
    repo: StubMatchRepository,
    thresholds: StubThresholdProvider | None = None,
    detector: StubDetector | None = None,
    embedder: StubEmbedder | None = None,
    media: StubMediaStore | None = None,
    extractor: StubFrameExtractor | None = None,
    top_k: int = 2,
    video_fps: float = 1.0,
) -> InferenceService:
    return InferenceService(
        media or StubMediaStore({"u": b"img", "v": b"vid"}),
        extractor or StubFrameExtractor([]),
        detector or StubDetector(mapping={b"img": [box()]}),
        embedder or StubEmbedder(),
        index,
        repo,
        thresholds or StubThresholdProvider(0.5, 0.1),
        top_k=top_k,
        video_fps=video_fps,
    )


def image_job() -> InferenceJob:
    return InferenceJob("media1", "u", "sch1", "ev1", MediaType.IMAGE)


def video_job() -> InferenceJob:
    return InferenceJob("media1", "v", "sch1", "ev1", MediaType.VIDEO)


async def test_image_single_match_records_all_fields() -> None:
    index = StubVectorIndex()
    index.script([Candidate("stu1", 0.95)])
    repo = StubMatchRepository()
    svc = make_service(index, repo=repo)

    outcome = await svc.process(image_job())

    assert outcome.matches_emitted == 1
    assert outcome.detector_version == "det-stub-1"
    assert outcome.embedding_model_version == "emb-stub-1"
    assert repo.save_calls == 1
    (rec,) = repo.saved_batches[0]
    assert rec.student_id == "stu1"
    assert (rec.school_id, rec.event_id, rec.media_id) == ("sch1", "ev1", "media1")
    assert rec.media_type == MediaType.IMAGE
    assert rec.confidence_score == 0.95
    assert rec.needs_review is False
    assert rec.frame_timestamp_ms is None
    assert rec.threshold_used == 0.5
    assert rec.gap_threshold_used == 0.1
    assert rec.embedding_model_version == "emb-stub-1"
    assert rec.detector_model_version == "det-stub-1"
    assert rec.bbox is not None


async def test_unknown_face_emits_no_record() -> None:
    index = StubVectorIndex()
    index.script([Candidate("stu1", 0.3)])  # below 0.5
    repo = StubMatchRepository()
    svc = make_service(index, repo=repo)

    outcome = await svc.process(image_job())

    assert outcome.matches_emitted == 0
    assert outcome.unknown_faces == 1
    assert repo.save_calls == 0  # save_batch not called for zero records


async def test_ambiguous_emits_both_needs_review() -> None:
    index = StubVectorIndex()
    index.script([Candidate("a", 0.9), Candidate("b", 0.85)])  # gap 0.05 < 0.1
    repo = StubMatchRepository()
    svc = make_service(index, repo=repo)

    outcome = await svc.process(image_job())

    assert outcome.matches_emitted == 2
    assert outcome.ambiguous_matches == 2
    assert all(r.needs_review for r in repo.saved_batches[0])


async def test_confident_gap_emits_single() -> None:
    index = StubVectorIndex()
    index.script([Candidate("a", 0.95), Candidate("b", 0.6)])  # gap 0.35 > 0.1
    repo = StubMatchRepository()
    svc = make_service(index, repo=repo)

    outcome = await svc.process(image_job())

    assert outcome.matches_emitted == 1
    assert repo.saved_batches[0][0].needs_review is False


async def test_dedupe_across_frames_keeps_best() -> None:
    index = StubVectorIndex()
    index.script([Candidate("stu1", 0.8)], [Candidate("stu1", 0.95)])
    repo = StubMatchRepository()
    frames = [Frame(b"f1", timestamp_ms=0), Frame(b"f2", timestamp_ms=1000)]
    detector = StubDetector(mapping={b"f1": [box()], b"f2": [box()]})
    svc = make_service(
        index, repo=repo, detector=detector, extractor=StubFrameExtractor(frames)
    )

    outcome = await svc.process(video_job())

    assert outcome.frames_processed == 2
    assert outcome.matches_emitted == 1
    rec = repo.saved_batches[0][0]
    assert rec.confidence_score == 0.95
    assert rec.frame_timestamp_ms == 1000  # the higher-confidence frame


async def test_thresholds_resolved_once_per_job() -> None:
    index = StubVectorIndex()
    index.script([Candidate("a", 0.9)], [Candidate("a", 0.9)])
    thresholds = StubThresholdProvider(0.5, 0.1)
    frames = [Frame(b"f1"), Frame(b"f2")]
    detector = StubDetector(mapping={b"f1": [box()], b"f2": [box()]})
    svc = make_service(
        index,
        repo=StubMatchRepository(),
        thresholds=thresholds,
        detector=detector,
        extractor=StubFrameExtractor(frames),
    )

    await svc.process(video_job())

    assert thresholds.calls == 1


async def test_job_for_unenrolled_school_matches_nothing() -> None:
    # Another school has a perfectly matching vector; a job for an empty school
    # must still match nobody (no cross-school leakage).
    index = StubVectorIndex()
    vector = normalized([1.0])
    await index.upsert("schoolB", "stuB", [vector], {})
    repo = StubMatchRepository()
    svc = make_service(
        index,
        repo=repo,
        detector=StubDetector(mapping={b"img": [box()]}),
        embedder=StubEmbedder(vector=vector),
    )

    outcome = await svc.process(InferenceJob("m", "u", "schoolA", "ev", MediaType.IMAGE))

    assert outcome.matches_emitted == 0


async def test_tenant_isolation_returns_only_same_school() -> None:
    index = StubVectorIndex()
    vector = normalized([1.0])
    await index.upsert("schoolA", "stuA", [vector], {})
    await index.upsert("schoolB", "stuB", [vector], {})
    repo = StubMatchRepository()
    svc = make_service(
        index,
        repo=repo,
        detector=StubDetector(mapping={b"img": [box()]}),
        embedder=StubEmbedder(vector=vector),
    )
    job = InferenceJob("m", "u", "schoolA", "ev", MediaType.IMAGE)

    outcome = await svc.process(job)

    assert outcome.matches_emitted == 1
    assert repo.saved_batches[0][0].student_id == "stuA"  # never stuB
    assert all(school == "schoolA" for school, _ in index.search_calls)


async def test_job_outcome_counts() -> None:
    index = StubVectorIndex()
    index.script([Candidate("a", 0.9)], [Candidate("b", 0.3)])  # face2 below threshold
    repo = StubMatchRepository()
    detector = StubDetector(mapping={b"img": [box(), box()]})  # two faces
    svc = make_service(index, repo=repo, detector=detector)

    outcome = await svc.process(image_job())

    assert outcome.faces_detected == 2
    assert outcome.frames_processed == 1
    assert outcome.candidates_above_threshold == 1
    assert outcome.matches_emitted == 1
    assert outcome.unknown_faces == 1


async def test_reprocessing_is_idempotent_higher_confidence_wins() -> None:
    # Validates the stub repo's ON-CONFLICT-higher-wins contract (the future
    # Postgres adapter's behaviour), not service code.
    repo = StubMatchRepository()
    media = StubMediaStore({"u": b"img"})
    detector = StubDetector(mapping={b"img": [box()]})

    def run(score: float) -> InferenceService:
        index = StubVectorIndex()
        index.script([Candidate("stu1", score)])
        return make_service(index, repo=repo, media=media, detector=detector)

    await run(0.8).process(image_job())
    await run(0.95).process(image_job())  # higher -> upgrades in place
    await run(0.6).process(image_job())  # lower -> no downgrade

    assert len(repo.rows) == 1
    assert repo.rows[("media1", "stu1")].confidence_score == 0.95


async def test_top_k_config_reaches_index() -> None:
    index = StubVectorIndex()
    index.script([Candidate("stu1", 0.95)])
    svc = make_service(index, repo=StubMatchRepository(), top_k=2)

    await svc.process(image_job())

    assert index.search_calls  # search actually happened (non-vacuous)
    assert all(top_k == 2 for _, top_k in index.search_calls)


async def test_video_fps_config_reaches_extractor() -> None:
    index = StubVectorIndex()
    index.script([Candidate("stu1", 0.95)])
    extractor = StubFrameExtractor([Frame(b"f1", timestamp_ms=0)])
    detector = StubDetector(mapping={b"f1": [box()]})
    svc = make_service(
        index,
        repo=StubMatchRepository(),
        detector=detector,
        extractor=extractor,
        video_fps=7.0,
    )

    await svc.process(video_job())

    assert any(fps == 7.0 for _, fps in extractor.calls)


async def test_video_with_no_frames_does_nothing() -> None:
    index = StubVectorIndex()
    repo = StubMatchRepository()
    svc = make_service(index, repo=repo, extractor=StubFrameExtractor([]))

    outcome = await svc.process(video_job())

    assert outcome.frames_processed == 0
    assert outcome.matches_emitted == 0
    assert repo.save_calls == 0


async def test_media_fetch_failure_propagates() -> None:
    index = StubVectorIndex()
    repo = StubMatchRepository()
    svc = make_service(index, repo=repo, media=StubMediaStore({}))  # "u" missing

    with pytest.raises(MediaFetchError):
        await svc.process(image_job())

    assert repo.save_calls == 0


async def test_embedder_failure_aborts_without_partial_write() -> None:
    index = StubVectorIndex()
    index.script([Candidate("stu1", 0.95)])
    repo = StubMatchRepository()
    svc = make_service(index, repo=repo, embedder=StubEmbedder(raise_for={b"img"}))

    with pytest.raises(RuntimeError):
        await svc.process(image_job())

    assert repo.save_calls == 0  # no partial write


async def test_multi_face_same_student_same_frame_dedupes() -> None:
    index = StubVectorIndex()
    index.script([Candidate("stu1", 0.9)], [Candidate("stu1", 0.95)])  # one per box
    repo = StubMatchRepository()
    detector = StubDetector(mapping={b"img": [box(), box()]})  # two faces, one frame
    svc = make_service(index, repo=repo, detector=detector)

    outcome = await svc.process(image_job())

    assert outcome.faces_detected == 2
    assert outcome.matches_emitted == 1  # deduped on (student_id, media_id)
    rec = repo.saved_batches[0][0]
    assert rec.student_id == "stu1"
    assert rec.confidence_score == 0.95  # higher of the two kept


async def test_single_face_duplicate_student_counts_once() -> None:
    index = StubVectorIndex()
    index.script([Candidate("stu1", 0.9), Candidate("stu1", 0.85)])  # same student twice
    repo = StubMatchRepository()
    svc = make_service(index, repo=repo)

    outcome = await svc.process(image_job())

    assert outcome.matches_emitted == 1
    assert outcome.candidates_above_threshold == 1  # distinct students, not rows
    rec = repo.saved_batches[0][0]
    assert rec.student_id == "stu1"
    assert rec.needs_review is False  # collapse -> single confident match


async def test_many_distinct_above_threshold_caps_emissions_at_two() -> None:
    # Three distinct students clear the threshold, but §6.2 emits at most the
    # top two; the counter still reflects all distinct students above threshold.
    index = StubVectorIndex()
    index.script([Candidate("a", 0.9), Candidate("b", 0.8), Candidate("c", 0.75)])
    repo = StubMatchRepository()
    svc = make_service(index, repo=repo, top_k=3)

    outcome = await svc.process(image_job())

    assert outcome.candidates_above_threshold == 3
    assert outcome.matches_emitted == 2


def test_invalid_config_is_rejected() -> None:
    with pytest.raises(ConfigurationError):
        make_service(StubVectorIndex(), repo=StubMatchRepository(), top_k=1)
    with pytest.raises(ConfigurationError):
        make_service(StubVectorIndex(), repo=StubMatchRepository(), video_fps=0)
