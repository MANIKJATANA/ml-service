"""InferenceService — the inference pipeline (requirements §4.2).

Depends only on domain ports + the shared identify kernel. Thresholds are resolved
once per job; the model versions used are snapshotted once and stamped on every
record (NFR-4). The per-frame "for every face, who is it?" work lives in
:func:`~ml_service.orchestration.identify.identify_in_frames` (shared with the dev
test UI so the two can never drift). This service persists two views of that pass
(decisions/0021): the deduped ``people`` map — best hit per ``(student_id,
media_id)`` (FR-I6) — as ``matches`` (``save_batch``, the only matches write path),
and the full per-face detection audit (media-centric, replace-by-media; opt out via
``persist_detections``). Search is strictly scoped to the job's ``school_id``
(FR-I4/NFR-3). Metrics come back as a ``JobOutcome`` for the worker to emit, so this
layer stays import-pure.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable

from ml_service.domain.errors import (
    ConfigurationError,
    EmbeddingVersionMismatch,
    MediaDecodeError,
    MediaFetchError,
)
from ml_service.domain.models import (
    BackendMedia,
    DetectionCandidate,
    DetectionOutcome,
    EventJob,
    EventOutcome,
    FaceDetectionRecord,
    Frame,
    FrameDetectionRecord,
    InferenceJob,
    JobOutcome,
    MatchRecord,
    MediaDetectionRecord,
    MediaType,
    Thresholds,
)
from ml_service.domain.ports import (
    BackendEventStore,
    DetectionRepository,
    FaceDetector,
    FaceEmbedder,
    MatchRepository,
    MediaStore,
    ThresholdProvider,
    VectorIndex,
    VideoFrameExtractor,
)
from ml_service.orchestration.identify import IdentifyResult, identify_in_frames

log = logging.getLogger(__name__)

_MEDIA_COMPLETED = "completed"  # backend media status the worker skips (decisions/0027)


class InferenceService:
    """Processes one media item into deduped matches + the per-face detection audit."""

    def __init__(
        self,
        media_store: MediaStore,
        extractor: VideoFrameExtractor,
        detector: FaceDetector,
        embedder: FaceEmbedder,
        index: VectorIndex,
        repo: MatchRepository,
        thresholds: ThresholdProvider,
        detection_repo: DetectionRepository,
        backend_store: BackendEventStore,
        *,
        top_k: int,
        video_fps: float,
        persist_detections: bool = True,
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
        self._detection_repo = detection_repo
        self._backend_store = backend_store
        self._top_k = top_k
        self._video_fps = video_fps
        self._persist_detections = persist_detections

    async def process_event(self, job: EventJob) -> EventOutcome:
        """Process one event: mark it ``processing``, read the backend's photo roster,
        run the per-photo pipeline on each not-yet-``completed`` photo (marking it
        ``completed`` as it finishes), then mark the event ``completed`` (decisions/0027).

        The ML worker owns these backend status writes, so the backend needs no poller.
        Idempotent: a redistribute re-runs every photo not yet ``completed`` (``completed``
        ones are skipped via the backend status column) — so a ``failed`` photo is
        **re-attempted** on the next Process. A per-photo fetch/decode/unexpected error is
        logged and the photo is marked ``failed`` (BP8a) — visible + retryable, so one bad
        photo never blocks the event. An ``EmbeddingVersionMismatch`` is systemic (stale
        index), so it aborts the whole event and propagates for the worker to nack + alert
        (the event stays ``processing`` and is retried on redelivery — nothing is marked
        failed, since it's the index that's wrong, not the photo).
        """
        await self._backend_store.mark_event_processing(job.school_id, job.event_id)
        roster = await self._backend_store.list_event_media(
            job.school_id, job.event_id
        )
        processed = skipped = failed = 0
        faces = candidates = matches = ambiguous = unknown = frames = 0
        for media in roster:
            if media.processing_status == _MEDIA_COMPLETED:
                skipped += 1
                continue
            try:
                outcome = await self.process(self._to_photo_job(job, media))
            except EmbeddingVersionMismatch:
                raise  # systemic — abort the event; worker nacks + alerts (§7.3/§8.4)
            except (MediaFetchError, MediaDecodeError) as exc:
                log.warning(
                    "marking photo failed after %s",
                    type(exc).__name__,
                    extra={"media_id": media.media_id, "event_id": job.event_id},
                )
                await self._backend_store.mark_media_failed(
                    job.school_id, media.media_id
                )
                failed += 1
                continue
            except Exception:
                log.exception(
                    "photo failed; marking failed",
                    extra={"media_id": media.media_id, "event_id": job.event_id},
                )
                await self._backend_store.mark_media_failed(
                    job.school_id, media.media_id
                )
                failed += 1
                continue
            # Persist per-photo completion on the backend row (its status column).
            await self._backend_store.mark_media_completed(
                job.school_id, media.media_id
            )
            processed += 1
            faces += outcome.faces_detected
            candidates += outcome.candidates_above_threshold
            matches += outcome.matches_emitted
            ambiguous += outcome.ambiguous_matches
            unknown += outcome.unknown_faces
            frames += outcome.frames_processed
        await self._backend_store.mark_event_completed(job.school_id, job.event_id)
        return EventOutcome(
            photos_total=len(roster),
            photos_processed=processed,
            photos_skipped=skipped,
            photos_failed=failed,
            faces_detected=faces,
            candidates_above_threshold=candidates,
            matches_emitted=matches,
            ambiguous_matches=ambiguous,
            unknown_faces=unknown,
            frames_processed=frames,
            detector_version=self._detector.version,
            embedding_model_version=self._embedder.version,
        )

    async def mark_event_failed(self, job: EventJob) -> None:
        """Flip a dead-lettered event to ``failed`` (BP19a) — the worker's DLQ consumer calls
        this so a stranded event stops looking like it's "processing" forever and becomes
        retryable. Idempotent (the same event can be drained/marked more than once)."""
        await self._backend_store.mark_event_failed(job.school_id, job.event_id)

    @staticmethod
    def _to_photo_job(job: EventJob, media: BackendMedia) -> InferenceJob:
        return InferenceJob(
            media_id=media.media_id,
            media_uri=media.media_uri,
            school_id=job.school_id,
            event_id=job.event_id,
            media_type=media.media_type,
        )

    async def process(self, job: InferenceJob) -> JobOutcome:
        """Process one media item end to end, returning a ``JobOutcome``.

        Thresholds and the detector/embedder model versions are snapshotted once
        per job (NFR-4). The per-frame identify pass yields the full timeline plus
        the deduped best-per-student map. Two views are persisted (decisions/0021):
        the deduped ``matches`` (one row per ``(student_id, media_id)``, highest
        confidence — locked NFR-5, via ``save_batch``) and, when
        ``persist_detections`` is on, the full per-face detection audit
        (media-centric, replace-by-media). The two write paths are each idempotent,
        so a partial failure self-heals on the worker's retry.
        """
        started = time.monotonic()
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

        # frames_matched: how many distinct frames each student was emitted in.
        frames_by_student: dict[str, set[int]] = {}
        for frame_index, frame_result in enumerate(result.frames):
            for face in frame_result.faces:
                for person in face.people:
                    frames_by_student.setdefault(person.student_id, set()).add(frame_index)

        # matches = the deduped best-per-student conclusion (locked contract, NFR-5).
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
                frames_matched=len(frames_by_student.get(student_id, ())),
            )
            for student_id, hit in result.people.items()
        ]
        if records:
            await self._repo.save_batch(records)  # only matches write path (§3.4)

        ambiguous = sum(1 for r in records if r.needs_review)
        # detections = the full media-centric evidence (every face, every candidate).
        if self._persist_detections:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            detection = self._build_detection_record(
                job,
                result,
                thresholds,
                detector_version=detector_version,
                embedding_version=embedding_version,
                matches_emitted=len(records),
                ambiguous_matches=ambiguous,
                processing_ms=elapsed_ms,
            )
            await self._detection_repo.save_detections(detection)

        return JobOutcome(
            faces_detected=result.faces_detected,
            candidates_above_threshold=result.candidates_above_threshold,
            matches_emitted=len(records),
            ambiguous_matches=ambiguous,
            unknown_faces=result.unknown_faces,
            frames_processed=result.frames_processed,
            detector_version=detector_version,
            embedding_model_version=embedding_version,
        )

    def _build_detection_record(
        self,
        job: InferenceJob,
        result: IdentifyResult,
        thresholds: Thresholds,
        *,
        detector_version: str,
        embedding_version: str,
        matches_emitted: int,
        ambiguous_matches: int,
        processing_ms: int | None,
    ) -> MediaDetectionRecord:
        """Map the identify pass's per-frame timeline into the detection audit tree.

        Every detected face becomes a ``FaceDetectionRecord``; every raw search
        candidate becomes a ``DetectionCandidate`` flagged with how the decision
        treated it (cleared threshold / emitted / needs review). ``result.frames`` is
        the media-centric view the kernel already returns (decisions/0021).
        """
        frame_records: list[FrameDetectionRecord] = []
        for frame_index, frame_result in enumerate(result.frames):
            face_records: list[FaceDetectionRecord] = []
            for face_index, face in enumerate(frame_result.faces):
                emitted_ids = {p.student_id for p in face.people}
                review_ids = {p.student_id for p in face.people if p.needs_review}
                candidates = tuple(
                    DetectionCandidate(
                        student_id=c.student_id,
                        score=c.score,
                        rank=rank,
                        cleared_threshold=thresholds.clears(c.score),
                        emitted=c.student_id in emitted_ids,
                        needs_review=c.student_id in review_ids,
                    )
                    for rank, c in enumerate(face.candidates, start=1)
                )
                if len(face.people) >= 2:
                    outcome = DetectionOutcome.AMBIGUOUS
                elif len(face.people) == 1:
                    outcome = DetectionOutcome.MATCH
                else:
                    outcome = DetectionOutcome.UNKNOWN
                face_records.append(
                    FaceDetectionRecord(
                        face_index=face_index,
                        box=face.bbox,
                        outcome=outcome,
                        candidates=candidates,
                    )
                )
            frame_records.append(
                FrameDetectionRecord(
                    frame_index=frame_index,
                    frame_timestamp_ms=frame_result.frame_timestamp_ms,
                    faces=tuple(face_records),
                )
            )
        video_fps = self._video_fps if job.media_type is MediaType.VIDEO else None
        return MediaDetectionRecord(
            school_id=job.school_id,
            event_id=job.event_id,
            media_id=job.media_id,
            media_type=job.media_type,
            media_uri=job.media_uri,
            video_fps=video_fps,
            frames_sampled=result.frames_processed,
            faces_detected=result.faces_detected,
            candidates_above_threshold=result.candidates_above_threshold,
            unknown_faces=result.unknown_faces,
            matches_emitted=matches_emitted,
            ambiguous_matches=ambiguous_matches,
            top_k=self._top_k,
            match_confidence_threshold=thresholds.match_confidence,
            gap_threshold=thresholds.gap,
            embedding_model_version=embedding_version,
            detector_model_version=detector_version,
            processing_ms=processing_ms,
            frames=tuple(frame_records),
        )
