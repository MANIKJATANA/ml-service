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
    BackendMedia,
    Candidate,
    DeadLetter,
    Embedding,
    EventJob,
    FaceBox,
    Frame,
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
    """Persists match records. ``save_batch`` is the only match-EMITTING write path;
    ``delete_by_student`` is the erasure path (BP8e, decisions/0053)."""

    async def save_batch(self, records: list[MatchRecord]) -> None: ...

    async def exists(self, media_id: str, student_id: str) -> bool: ...

    async def delete_by_student(self, school_id: str, student_id: str) -> None:
        """Purge every match for one student (erasure). Tenant-scoped by ``school_id``."""
        ...


class DetectionRepository(Protocol):
    """Persists the full per-face detection audit for a media (decisions/0021).

    ``save_detections`` replaces every row for the media (delete + insert in one
    transaction, FK cascade) — the per-media detection set is regenerated
    deterministically. Kept separate from ``MatchRepository`` so that repo's
    "``save_batch`` is the only write path" invariant stays intact.
    ``delete_candidates_by_student`` is the erasure path (BP8e, decisions/0053).
    """

    async def save_detections(self, detection: MediaDetectionRecord) -> None: ...

    async def delete_candidates_by_student(
        self, school_id: str, student_id: str
    ) -> None:
        """Purge a student's per-face candidate rows (erasure). The media-centric parents
        (media_detections/media_frames/face_detections) stay — they're shared across the
        students in a media. Keyed on the globally-unique ``student_id``."""
        ...


class BackendEventStore(Protocol):
    """The worker's read+write view of the backend's ``events``/``media`` status columns
    over the shared DB (decisions/0027). The ML worker **owns the status writes** — it
    flips the event ``processing``→``completed`` and each photo ``pending``→``completed``
    — and the backend just reads them (no poller). This is the coupling to the backend
    schema (mirror of the backend reading ML's tables); the ML service never calls the
    backend over HTTP.
    """

    async def list_event_media(
        self, school_id: str, event_id: str
    ) -> list[BackendMedia]: ...
    async def mark_media_completed(self, school_id: str, media_id: str) -> None: ...
    async def mark_media_failed(self, school_id: str, media_id: str) -> None: ...
    async def mark_event_processing(self, school_id: str, event_id: str) -> None: ...
    async def mark_event_completed(self, school_id: str, event_id: str) -> None: ...
    # BP19a: the event's job dead-lettered — mark it `failed` (visible + retryable).
    async def mark_event_failed(self, school_id: str, event_id: str) -> None: ...


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
    """At-least-once event-job queue with explicit ack/nack (architecture §8.4)."""

    async def enqueue(self, job: EventJob) -> None: ...

    def consume(self) -> AsyncIterator[JobLease]: ...

    async def ack(self, lease: JobLease) -> None: ...

    async def nack(self, lease: JobLease) -> None: ...

    async def drain_dead_letters(self) -> list[DeadLetter]:
        """Read the currently-accumulated dead-letter entries (BP19a) — WITHOUT removing the
        actionable ones (a malformed entry, which names no event, is dropped in place).

        The worker's DLQ consumer marks each returned event ``failed`` and then calls
        ``remove_dead_letter`` — mark-before-remove, so a crash mid-drain re-marks the same
        events idempotently on the next drain rather than losing the failure. Reading (not
        acking) is safe because ``mark_event_failed`` is idempotent."""
        ...

    async def remove_dead_letter(self, receipt: str) -> None:
        """Remove one dead-letter entry after its event has been marked ``failed`` (BP19a)."""
        ...

    async def dead_letter_depth(self) -> int:
        """How many entries are in the dead-letter stream right now (BP19b — a gauge)."""
        ...

    async def oldest_pending_age_ms(self) -> float | None:
        """Age (ms) of the oldest in-flight (pending, unacked) job, or ``None`` if the stream
        is idle (BP19b — a gauge; the queue-lag / stuck-worker signal)."""
        ...
