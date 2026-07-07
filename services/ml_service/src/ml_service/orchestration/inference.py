"""InferenceService — the inference pipeline (requirements §4.2).

Depends only on domain ports + the shared identify kernel. Thresholds are resolved
once per job; the model versions used are snapshotted once and stamped on every
record (NFR-4). The per-frame "for every face, who is it?" work lives in
:func:`~ml_service.orchestration.identify.identify_in_frames` (shared with the dev
test UI so the two can never drift). This service reduces that pass's deduped
``people`` map — best hit per ``(student_id, media_id)`` (FR-I6) — into match
records; ``save_batch`` is the only write path. Search is strictly scoped to the
job's ``school_id`` (FR-I4/NFR-3). Metrics come back as a ``JobOutcome`` for the
worker to emit, so this layer stays import-pure.
"""

from __future__ import annotations

from collections.abc import Iterable

from ml_service.domain.errors import ConfigurationError
from ml_service.domain.models import (
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
from ml_service.orchestration.identify import identify_in_frames


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
        per job (NFR-4). The per-frame identify pass yields the full timeline plus
        the deduped best-per-student map; this method persists only the deduped map
        (one row per ``(student_id, media_id)``, highest confidence — the locked
        idempotency contract, NFR-5). ``save_batch`` is the only write path.
        """
        media_bytes = await self._media_store.fetch(job.media_uri)
        thresholds = await self._thresholds.get_thresholds(job.school_id)  # once per job
        detector_version = self._detector.version
        embedding_version = self._embedder.version  # snapshot once (NFR-4)

        if job.media_type is MediaType.VIDEO:
            frames: Iterable[Frame] = self._extractor.extract(media_bytes, self._video_fps)
        else:
            frames = [Frame(media_bytes)]

        result = await identify_in_frames(
            frames,
            school_id=job.school_id,
            detector=self._detector,
            embedder=self._embedder,
            index=self._index,
            thresholds=thresholds,
            top_k=self._top_k,
        )

        # result.frames carries the full per-frame/per-face timeline; the worker
        # persists only the deduped best-per-student (locked matches contract). The
        # per-frame detail is the hook for a future match_detections table (0020).
        records = [
            MatchRecord(
                school_id=job.school_id,
                event_id=job.event_id,
                student_id=student_id,
                media_id=job.media_id,
                media_type=job.media_type,
                confidence_score=hit.score,
                needs_review=hit.needs_review,
                embedding_model_version=embedding_version,
                detector_model_version=detector_version,
                threshold_used=thresholds.match_confidence,
                gap_threshold_used=thresholds.gap,
                bbox=hit.bbox,
                frame_timestamp_ms=hit.frame_timestamp_ms,
            )
            for student_id, hit in result.people.items()
        ]
        if records:
            await self._repo.save_batch(records)  # only write path (architecture §3.4)

        return JobOutcome(
            faces_detected=result.faces_detected,
            candidates_above_threshold=result.candidates_above_threshold,
            matches_emitted=len(records),
            ambiguous_matches=sum(1 for r in records if r.needs_review),
            unknown_faces=result.unknown_faces,
            frames_processed=result.frames_processed,
            detector_version=detector_version,
            embedding_model_version=embedding_version,
        )
