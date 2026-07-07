"""Ports — abstract interfaces (Protocols) the orchestration layer depends on.

Pure: no third-party imports. Concrete adapters live in ``ml_service.adapters``
and are wired in ``ml_service.wiring``. Requirements §9 defines eight ports; a
ninth, ``ReferencePhotoRepository``, backs the student-id-triggered enrollment
contract (see decisions/0009). Ports are async (sync ML work is offloaded inside
adapters) except ``VideoFrameExtractor``, which stays a lazy sync iterator.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping
from typing import Protocol

from ml_service.domain.models import (
    Candidate,
    Embedding,
    FaceBox,
    Frame,
    InferenceJob,
    JobLease,
    MatchRecord,
    MediaDetectionRecord,
    Thresholds,
)


class FaceDetector(Protocol):
    """Detects faces in an image."""

    version: str

    async def detect(self, image_bytes: bytes) -> list[FaceBox]: ...


class FaceEmbedder(Protocol):
    """Produces an L2-normalized embedding for a detected face."""

    version: str

    async def embed(self, image_bytes: bytes, face_box: FaceBox) -> Embedding: ...


class VectorIndex(Protocol):
    """Per-school vector store. Every call is scoped by ``school_id`` (tenant
    isolation, NFR-3).

    ``upsert`` atomically *replaces* a student's vectors (FR-E3). ``search``
    returns candidates **sorted by score descending and at most one per
    ``student_id``** (the student's best hit).

    Phase-2 faiss-adapter note: under multi-vector enrollment a student owns
    several vectors, so a raw top-k search can return the same ``student_id``
    multiple times (and let one student fill both decision slots, masking a true
    second match). The adapter must therefore **over-fetch** (k' > ``top_k``) and
    **collapse per student** (keep each student's best) before returning ``top_k``.
    Likewise replace-not-append (FR-E3) means ``upsert``/``delete`` must remove
    **all** rows for a student: architecture §7.4 says "old row" (singular), but
    multi-vector enrollment makes that all rows per student.
    """

    async def upsert(
        self,
        school_id: str,
        student_id: str,
        embeddings: list[Embedding],
        metadata: Mapping[str, object],
    ) -> None: ...

    async def search(
        self, school_id: str, embedding: Embedding, top_k: int
    ) -> list[Candidate]:
        """Return up to ``top_k`` candidates, sorted by score descending and at
        most one per ``student_id`` (the student's best hit)."""
        ...

    async def delete(self, school_id: str, student_id: str) -> None: ...


class MediaStore(Protocol):
    """Fetches media bytes from a URI (Supabase Storage, local FS, ...)."""

    async def fetch(self, media_uri: str) -> bytes: ...


class VideoFrameExtractor(Protocol):
    """Lazily yields frames sampled from a video at a fixed FPS (req §9)."""

    def extract(self, video_bytes: bytes, fps: float) -> Iterator[Frame]: ...


class MatchRepository(Protocol):
    """Persists match records. ``save_batch`` is the only write path."""

    async def save_batch(self, records: list[MatchRecord]) -> None: ...

    async def exists(self, media_id: str, student_id: str) -> bool: ...


class DetectionRepository(Protocol):
    """Persists the full per-face detection audit for a media (decisions/0021).

    ``save_detections`` replaces every row for the media (delete + insert in one
    transaction, FK cascade) — the per-media detection set is regenerated
    deterministically. Kept separate from ``MatchRepository`` so that repo's
    "``save_batch`` is the only write path" invariant stays intact.
    """

    async def save_detections(self, detection: MediaDetectionRecord) -> None: ...


class ThresholdProvider(Protocol):
    """Resolves per-school thresholds with global-default fallback (req §6.1)."""

    async def get_thresholds(self, school_id: str) -> Thresholds: ...


class ReferencePhotoRepository(Protocol):
    """Stores the reference-photo URIs for a student (enroll-by-id contract)."""

    async def get(self, school_id: str, student_id: str) -> list[str]: ...

    async def replace(
        self, school_id: str, student_id: str, photo_uris: list[str]
    ) -> None: ...

    async def delete(self, school_id: str, student_id: str) -> None: ...


class JobQueue(Protocol):
    """At-least-once job queue with explicit ack/nack (architecture §8.4)."""

    async def enqueue(self, job: InferenceJob) -> None: ...

    def consume(self) -> AsyncIterator[JobLease]: ...

    async def ack(self, lease: JobLease) -> None: ...

    async def nack(self, lease: JobLease) -> None: ...
