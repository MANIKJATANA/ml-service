"""InferenceService — the inference pipeline (requirements §4.2).

Depends only on domain ports + the pure decision function. Thresholds are
resolved once per job; the model versions used are snapshotted once and stamped
on every record (NFR-4); detections are deduped per ``(student_id, media_id)``
keeping the highest-confidence hit (FR-I6); search is strictly scoped to the
job's ``school_id`` (FR-I4/NFR-3). ``save_batch`` is the only write path. Metrics
are returned as a ``JobOutcome`` for the worker to emit, so this layer stays
import-pure.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from ml_service.domain.decision import apply_threshold_and_gap
from ml_service.domain.errors import ConfigurationError
from ml_service.domain.models import (
    FaceBox,
    Frame,
    InferenceJob,
    JobOutcome,
    MatchRecord,
    MediaType,
)
from ml_service.domain.ports import (
    FaceDetector,
    FaceEmbedder,
    MatchRepository,
    MediaStore,
    ThresholdProvider,
    VectorIndex,
    VideoFrameExtractor,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Best:
    """The best detection seen so far for one ``(student_id, media_id)`` key."""

    score: float
    needs_review: bool
    bbox: FaceBox
    frame_timestamp_ms: int | None


class InferenceService:
    """Processes one media item into deduped match records."""

    def __init__(
        self,
        media_store: MediaStore,
        extractor: VideoFrameExtractor,
        detector: FaceDetector,
        embedder: FaceEmbedder,
        index: VectorIndex,
        repo: MatchRepository,
        thresholds: ThresholdProvider,
        *,
        top_k: int,
        video_fps: float,
    ) -> None:
        if top_k < 2:
            raise ConfigurationError(
                f"top_k must be >= 2 for the gap decision (locked §8.2); got {top_k}"
            )
        if video_fps <= 0:
            raise ConfigurationError(f"video_fps must be > 0; got {video_fps}")
        self._media_store = media_store
        self._extractor = extractor
        self._detector = detector
        self._embedder = embedder
        self._index = index
        self._repo = repo
        self._thresholds = thresholds
        self._top_k = top_k
        self._video_fps = video_fps

    async def process(self, job: InferenceJob) -> JobOutcome:
        """Process one media item end to end, returning a ``JobOutcome``.

        Thresholds and the detector/embedder model versions are snapshotted once
        per job (NFR-4); detections are deduped per ``(student_id, media_id)``
        keeping the highest-confidence hit; ``save_batch`` is the only write path.
        """
        media_bytes = await self._media_store.fetch(job.media_uri)
        thresholds = await self._thresholds.get_thresholds(job.school_id)  # once per job
        detector_version = self._detector.version
        embedding_version = self._embedder.version  # snapshot once (NFR-4)

        if job.media_type is MediaType.VIDEO:
            frames: Iterable[Frame] = self._extractor.extract(media_bytes, self._video_fps)
        else:
            frames = [Frame(media_bytes)]

        best: dict[tuple[str, str], _Best] = {}
        faces_detected = 0
        candidates_above_threshold = 0
        unknown_faces = 0
        frames_processed = 0

        for frame in frames:
            frames_processed += 1
            boxes = await self._detector.detect(frame.image_bytes)
            faces_detected += len(boxes)
            for box in boxes:
                embedding = await self._embedder.embed(frame.image_bytes, box)
                candidates = await self._index.search(job.school_id, embedding, self._top_k)
                candidates_above_threshold += len(
                    {c.student_id for c in candidates if thresholds.clears(c.score)}
                )
                emissions = apply_threshold_and_gap(candidates, thresholds)
                if not emissions:  # unknown face — log only, no record (FR-I8)
                    unknown_faces += 1
                    continue
                for emission in emissions:
                    key = (emission.candidate.student_id, job.media_id)
                    current = best.get(key)
                    if current is None or emission.candidate.score > current.score:
                        best[key] = _Best(
                            emission.candidate.score,
                            emission.needs_review,
                            box,
                            frame.timestamp_ms,
                        )

        records = [
            MatchRecord(
                school_id=job.school_id,
                event_id=job.event_id,
                student_id=student_id,
                media_id=media_id,
                media_type=job.media_type,
                confidence_score=entry.score,
                needs_review=entry.needs_review,
                embedding_model_version=embedding_version,
                detector_model_version=detector_version,
                threshold_used=thresholds.match_confidence,
                gap_threshold_used=thresholds.gap,
                bbox=entry.bbox,
                frame_timestamp_ms=entry.frame_timestamp_ms,
            )
            for (student_id, media_id), entry in best.items()
        ]
        if records:
            await self._repo.save_batch(records)  # only write path (architecture §3.4)

        return JobOutcome(
            faces_detected=faces_detected,
            candidates_above_threshold=candidates_above_threshold,
            matches_emitted=len(records),
            ambiguous_matches=sum(1 for r in records if r.needs_review),
            unknown_faces=unknown_faces,
            frames_processed=frames_processed,
            detector_version=detector_version,
            embedding_model_version=embedding_version,
        )
