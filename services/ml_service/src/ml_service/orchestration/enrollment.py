"""EnrollmentService — synchronous enrollment pipeline (requirements §4.1).

Depends only on domain ports. Student-id-triggered: reference-photo URIs are
resolved from the ``ReferencePhotoRepository`` and fetched via the ``MediaStore``
(see decisions/0009). Per-photo failures are isolated (FR-E4); enrollment is
replace-not-append (FR-E3).
"""

from __future__ import annotations

import logging

from ml_service.domain.errors import EnrollmentError
from ml_service.domain.models import (
    EMBEDDING_DIM,
    SIMILARITY_METRIC,
    Embedding,
    EnrollmentResult,
    PhotoResult,
    PhotoStatus,
)
from ml_service.domain.ports import (
    DetectionRepository,
    FaceDetector,
    FaceEmbedder,
    MatchRepository,
    MediaStore,
    ReferencePhotoRepository,
    VectorIndex,
)

log = logging.getLogger(__name__)


class EnrollmentService:
    """Detects + embeds a student's reference photos and upserts them into the
    per-school vector index."""

    def __init__(
        self,
        reference_photos: ReferencePhotoRepository,
        media_store: MediaStore,
        detector: FaceDetector,
        embedder: FaceEmbedder,
        index: VectorIndex,
        matches: MatchRepository,
        detections: DetectionRepository,
    ) -> None:
        self._reference_photos = reference_photos
        self._media_store = media_store
        self._detector = detector
        self._embedder = embedder
        self._index = index
        self._matches = matches
        self._detections = detections

    async def enroll(
        self,
        school_id: str,
        student_id: str,
        photo_uris: list[str] | None = None,
    ) -> EnrollmentResult:
        """Enroll or refresh a student.

        If ``photo_uris`` is given, it replaces the stored reference-photo URIs
        first; otherwise the existing URIs are used (a refresh). An explicitly
        empty ``photo_uris`` is rejected (clearing a student is ``delete()``'s
        job, not enrollment's). Each photo is fetched, detected, the largest face
        embedded, and all embeddings are upserted as one atomic replace. Per-photo
        failures don't abort the rest.
        """
        if photo_uris is not None and len(photo_uris) == 0:
            # Reject before replace() so stored URIs are not silently wiped.
            raise EnrollmentError("empty photo_uris; use delete() to remove a student")
        if photo_uris is not None:
            await self._reference_photos.replace(school_id, student_id, photo_uris)
        uris = await self._reference_photos.get(school_id, student_id)
        uris = list(dict.fromkeys(uris))  # order-preserving dedup: never embed a photo twice

        embeddings: list[Embedding] = []
        results: list[PhotoResult] = []
        for i, uri in enumerate(uris):
            result, embedding = await self._embed_one(i, uri, school_id, student_id)
            results.append(result)
            if embedding is not None:
                embeddings.append(embedding)

        if embeddings:  # replace-not-append (FR-E3); never wipe prior on all-fail
            await self._index.upsert(
                school_id,
                student_id,
                embeddings,
                {
                    "embedding_model_version": self._embedder.version,
                    "dim": EMBEDDING_DIM,
                    "metric": SIMILARITY_METRIC,
                },
            )
        return EnrollmentResult(school_id, student_id, len(embeddings), tuple(results))

    async def _embed_one(
        self,
        photo_index: int,
        uri: str,
        school_id: str,
        student_id: str,
    ) -> tuple[PhotoResult, Embedding | None]:
        """Process a single reference photo without mutating caller state.

        Returns the per-photo status and, on success, its embedding (else
        ``None``); isolates any failure (FR-E4).
        """
        try:
            image_bytes = await self._media_store.fetch(uri)
            boxes = await self._detector.detect(image_bytes)
            if not boxes:
                return PhotoResult(photo_index, PhotoStatus.NO_FACE), None
            box = max(boxes, key=lambda b: b.area)
            status = PhotoStatus.ENROLLED
            if len(boxes) > 1:  # pick largest, log a warning (req §8.7)
                log.warning(
                    "multiple faces in reference photo; picking largest",
                    extra={
                        "school_id": school_id,
                        "student_id": student_id,
                        "photo_index": photo_index,
                        "faces": len(boxes),
                    },
                )
                status = PhotoStatus.MULTIPLE_FACES
            embedding = await self._embedder.embed(image_bytes, box)
            return PhotoResult(photo_index, status), embedding
        except Exception as exc:  # noqa: BLE001 — per-photo isolation (FR-E4)
            log.warning(
                "reference photo failed",
                exc_info=exc,
                extra={
                    "school_id": school_id,
                    "student_id": student_id,
                    "photo_index": photo_index,
                },
            )
            return PhotoResult(photo_index, PhotoStatus.ERROR, str(exc)), None

    async def delete(self, school_id: str, student_id: str) -> None:
        """Erase a student's entire ML footprint (FR-E2 + BP8e, decisions/0053): the FAISS
        embeddings, the stored reference-photo URIs, the ``matches`` rows, and the per-face
        detection-audit candidate rows naming them. The media-centric detection parents stay
        (they belong to the media, shared across students)."""
        await self._index.delete(school_id, student_id)
        await self._reference_photos.delete(school_id, student_id)
        await self._matches.delete_by_student(school_id, student_id)
        await self._detections.delete_candidates_by_student(school_id, student_id)
