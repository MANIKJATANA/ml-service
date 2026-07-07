"""The shared identify kernel — detect → embed → search → decide, per frame.

This is the single place the "for every face in every frame, who is it?" loop
lives. Both the inference worker (:class:`~ml_service.orchestration.inference.
InferenceService`) and the dev test UI call it, so identification can never drift
between "what the worker persists" and "what the UI shows".

It returns **two views of the same pass** so each caller takes what it needs:

* ``frames`` — the full **per-frame / per-face** timeline: every sampled frame
  (its ``frame_timestamp_ms``), the faces detected in it, and the person(s) each
  face matched (or none = unknown). This is what the test UI renders for video,
  and the hook a future ``match_detections`` table would persist (decisions/0020).
* ``people`` — the media collapsed to the **best hit per student** (highest score
  wins). This reproduces the worker's locked ``(student_id, media_id)`` dedupe
  exactly (``media_id`` is constant within a job), so it stays the sole input to
  the deduped ``matches`` write.

Pure orchestration: imports only ``domain`` (decision + ports + models). Thresholds
are resolved **once** by the caller and passed in by value (NFR-4); the kernel never
touches a provider, a repository, or the clock.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ml_service.domain.decision import apply_threshold_and_gap
from ml_service.domain.models import FaceBox, Frame, Thresholds
from ml_service.domain.ports import FaceDetector, FaceEmbedder, VectorIndex


@dataclass(frozen=True, slots=True)
class PersonHit:
    """One person matched on one face, with the face's location + time."""

    student_id: str
    score: float
    needs_review: bool
    bbox: FaceBox
    frame_timestamp_ms: int | None  # None for a still image


@dataclass(frozen=True, slots=True)
class FaceResult:
    """One detected face and the decision for it (req §6.2).

    ``people`` holds 0 hits (unknown face — below threshold / no match), 1 hit (a
    confident match), or 2 hits (ambiguous: both carry ``needs_review=True``).
    """

    bbox: FaceBox
    people: list[PersonHit]


@dataclass(frozen=True, slots=True)
class FrameResult:
    """One sampled video frame (or the single still image) and its faces."""

    frame_timestamp_ms: int | None
    faces: list[FaceResult]


@dataclass(frozen=True, slots=True)
class IdentifyResult:
    """Both views of one identify pass; plus the counters for ``JobOutcome``."""

    frames: list[FrameResult] = field(default_factory=list)
    people: dict[str, PersonHit] = field(default_factory=dict)
    faces_detected: int = 0
    candidates_above_threshold: int = 0
    unknown_faces: int = 0
    frames_processed: int = 0


async def identify_in_frames(
    frames: Iterable[Frame],
    *,
    school_id: str,
    detector: FaceDetector,
    embedder: FaceEmbedder,
    index: VectorIndex,
    thresholds: Thresholds,
    top_k: int,
) -> IdentifyResult:
    """Identify every face in every frame; return per-frame detail + deduped people.

    Search is strictly scoped to ``school_id`` (tenant isolation, FR-I4/NFR-3).
    ``thresholds`` is already resolved for this job (once, by the caller).
    """
    best: dict[str, PersonHit] = {}
    frame_results: list[FrameResult] = []
    faces_detected = 0
    candidates_above_threshold = 0
    unknown_faces = 0
    frames_processed = 0

    for frame in frames:
        frames_processed += 1
        boxes = await detector.detect(frame.image_bytes)
        faces_detected += len(boxes)
        face_results: list[FaceResult] = []
        for box in boxes:
            embedding = await embedder.embed(frame.image_bytes, box)
            candidates = await index.search(school_id, embedding, top_k)
            candidates_above_threshold += len(
                {c.student_id for c in candidates if thresholds.clears(c.score)}
            )
            emissions = apply_threshold_and_gap(candidates, thresholds)
            if not emissions:  # unknown face — recorded as a face with no people
                unknown_faces += 1
                face_results.append(FaceResult(bbox=box, people=[]))
                continue
            hits = [
                PersonHit(
                    student_id=e.candidate.student_id,
                    score=e.candidate.score,
                    needs_review=e.needs_review,
                    bbox=box,
                    frame_timestamp_ms=frame.timestamp_ms,
                )
                for e in emissions
            ]
            face_results.append(FaceResult(bbox=box, people=hits))
            for hit in hits:  # dedupe to the best hit per student (highest score)
                current = best.get(hit.student_id)
                if current is None or hit.score > current.score:
                    best[hit.student_id] = hit
        frame_results.append(
            FrameResult(frame_timestamp_ms=frame.timestamp_ms, faces=face_results)
        )

    return IdentifyResult(
        frames=frame_results,
        people=best,
        faces_detected=faces_detected,
        candidates_above_threshold=candidates_above_threshold,
        unknown_faces=unknown_faces,
        frames_processed=frames_processed,
    )
