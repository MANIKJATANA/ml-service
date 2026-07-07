"""identify_in_frames kernel: per-frame/per-face detail + deduped people.

The kernel is the single face→person loop shared by the inference worker and the
dev test UI. These tests pin the two views it returns: the ``frames`` timeline
(every sampled frame → its faces → who) and the ``people`` map (best hit per
student). A person seen in several frames must appear in EACH frame's result yet
only ONCE in ``people`` — the crux of "per-frame for video, not globally unique".
"""

from fakes import StubDetector, StubEmbedder, StubVectorIndex, box
from ml_service.domain.models import Candidate, Frame, Thresholds
from ml_service.orchestration.identify import IdentifyResult, identify_in_frames

THRESHOLDS = Thresholds(match_confidence=0.5, gap=0.1)


async def _run(
    frames: list[Frame], index: StubVectorIndex, *, detector: StubDetector, top_k: int = 2
) -> IdentifyResult:
    return await identify_in_frames(
        frames,
        school_id="sch1",
        detector=detector,
        embedder=StubEmbedder(),
        index=index,
        thresholds=THRESHOLDS,
        top_k=top_k,
    )


async def test_per_frame_structure_preserves_timestamps() -> None:
    index = StubVectorIndex()
    index.script([Candidate("a", 0.9)], [Candidate("b", 0.8)])
    frames = [Frame(b"f1", timestamp_ms=0), Frame(b"f2", timestamp_ms=1000)]
    detector = StubDetector(mapping={b"f1": [box()], b"f2": [box()]})

    result = await _run(frames, index, detector=detector)

    assert result.frames_processed == 2
    assert [fr.frame_timestamp_ms for fr in result.frames] == [0, 1000]
    assert [len(fr.faces) for fr in result.frames] == [1, 1]
    assert result.frames[0].faces[0].people[0].student_id == "a"
    assert result.frames[0].faces[0].people[0].frame_timestamp_ms == 0
    assert result.frames[1].faces[0].people[0].student_id == "b"
    assert result.frames[1].faces[0].people[0].frame_timestamp_ms == 1000


async def test_person_across_frames_listed_each_frame_but_deduped_in_people() -> None:
    index = StubVectorIndex()
    index.script([Candidate("a", 0.8)], [Candidate("a", 0.95)])
    frames = [Frame(b"f1", timestamp_ms=0), Frame(b"f2", timestamp_ms=1000)]
    detector = StubDetector(mapping={b"f1": [box()], b"f2": [box()]})

    result = await _run(frames, index, detector=detector)

    # Per-frame timeline: 'a' appears at BOTH timestamps (not globally deduped).
    assert result.frames[0].faces[0].people[0].student_id == "a"
    assert result.frames[1].faces[0].people[0].student_id == "a"
    # Deduped summary: 'a' once, at the best score + that frame's timestamp.
    assert set(result.people) == {"a"}
    assert result.people["a"].score == 0.95
    assert result.people["a"].frame_timestamp_ms == 1000


async def test_multiple_faces_one_frame_yields_multiple_people() -> None:
    index = StubVectorIndex()
    index.script([Candidate("a", 0.9)], [Candidate("b", 0.85)])
    detector = StubDetector(mapping={b"img": [box(), box()]})

    result = await _run([Frame(b"img")], index, detector=detector)

    assert result.faces_detected == 2
    assert len(result.frames) == 1
    assert len(result.frames[0].faces) == 2
    assert result.frames[0].faces[0].people[0].student_id == "a"
    assert result.frames[0].faces[1].people[0].student_id == "b"
    assert set(result.people) == {"a", "b"}


async def test_unknown_face_has_empty_people_and_is_counted() -> None:
    index = StubVectorIndex()
    index.script([Candidate("a", 0.3)])  # below the 0.5 threshold
    detector = StubDetector(mapping={b"img": [box()]})

    result = await _run([Frame(b"img")], index, detector=detector)

    assert result.faces_detected == 1
    assert result.unknown_faces == 1
    assert result.frames[0].faces[0].people == []
    assert result.people == {}


async def test_ambiguous_face_lists_two_people_needs_review() -> None:
    index = StubVectorIndex()
    index.script([Candidate("a", 0.9), Candidate("b", 0.85)])  # gap 0.05 < 0.1
    detector = StubDetector(mapping={b"img": [box()]})

    result = await _run([Frame(b"img")], index, detector=detector)

    face = result.frames[0].faces[0]
    assert [p.student_id for p in face.people] == ["a", "b"]
    assert all(p.needs_review for p in face.people)
    assert set(result.people) == {"a", "b"}
    assert result.candidates_above_threshold == 2


async def test_still_image_is_single_frame_without_timestamp() -> None:
    index = StubVectorIndex()
    index.script([Candidate("a", 0.9)])
    detector = StubDetector(mapping={b"img": [box()]})

    result = await _run([Frame(b"img")], index, detector=detector)

    assert len(result.frames) == 1
    assert result.frames[0].frame_timestamp_ms is None
    assert result.people["a"].frame_timestamp_ms is None


async def test_frame_with_no_faces_is_still_recorded() -> None:
    index = StubVectorIndex()
    detector = StubDetector(mapping={b"empty": []})

    result = await _run([Frame(b"empty", timestamp_ms=500)], index, detector=detector)

    assert result.frames_processed == 1
    assert result.faces_detected == 0
    assert result.frames[0].frame_timestamp_ms == 500
    assert result.frames[0].faces == []
    assert result.people == {}
