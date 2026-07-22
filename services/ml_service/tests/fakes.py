"""Deterministic, test-only port doubles.

NOT part of the shipped service — the layering test (``tests/test_layering.py``)
forbids ``domain``/``orchestration`` from importing this module. These stubs feed
the orchestration services controlled inputs (exact scores, frame counts, failure
points) that real face images cannot reproduce deterministically. Real-adapter
behaviour is covered by the Phase 2 adapter + e2e tests.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping, Sequence

from ml_service.domain.errors import MediaFetchError
from ml_service.domain.models import (
    EMBEDDING_DIM,
    BackendMedia,
    Candidate,
    Embedding,
    FaceBox,
    Frame,
    MatchRecord,
    MediaDetectionRecord,
    Thresholds,
)


def normalized(values: Sequence[float]) -> Embedding:
    """Build an L2-normalized 512-d Embedding from leading values (zero-padded)."""
    padded = list(values) + [0.0] * (EMBEDDING_DIM - len(values))
    norm = math.sqrt(sum(v * v for v in padded)) or 1.0
    return Embedding(tuple(v / norm for v in padded))


def box(score: float = 0.99, size: float = 100.0) -> FaceBox:
    """A square FaceBox at the origin with the given side length and score."""
    return FaceBox(0.0, 0.0, size, size, score)


def _dot(a: Embedding, b: Embedding) -> float:
    return sum(x * y for x, y in zip(a.vector, b.vector, strict=True))


class StubReferencePhotoRepository:
    def __init__(self) -> None:
        self._store: dict[tuple[str, str], list[str]] = {}

    async def get(self, school_id: str, student_id: str) -> list[str]:
        return list(self._store.get((school_id, student_id), []))

    async def replace(
        self, school_id: str, student_id: str, photo_uris: list[str]
    ) -> None:
        self._store[(school_id, student_id)] = list(photo_uris)

    async def delete(self, school_id: str, student_id: str) -> None:
        self._store.pop((school_id, student_id), None)


class StubMediaStore:
    def __init__(self, data: dict[str, bytes] | None = None) -> None:
        self.data: dict[str, bytes] = dict(data or {})

    async def fetch(self, media_uri: str) -> bytes:
        try:
            return self.data[media_uri]
        except KeyError as exc:
            raise MediaFetchError(media_uri) from exc


class StubDetector:
    def __init__(
        self,
        boxes: list[FaceBox] | None = None,
        mapping: dict[bytes, list[FaceBox]] | None = None,
        version: str = "det-stub-1",
    ) -> None:
        self.version = version
        self._boxes = boxes
        self._mapping = mapping or {}
        self.calls: list[bytes] = []

    async def detect(self, image_bytes: bytes) -> list[FaceBox]:
        self.calls.append(image_bytes)
        if image_bytes in self._mapping:
            return list(self._mapping[image_bytes])
        return list(self._boxes) if self._boxes is not None else [box()]


class StubEmbedder:
    def __init__(
        self,
        vector: Embedding | None = None,
        mapping: dict[bytes, Embedding] | None = None,
        raise_for: set[bytes] | None = None,
        version: str = "emb-stub-1",
    ) -> None:
        self.version = version
        self._vector = vector if vector is not None else normalized([1.0])
        self._mapping = mapping or {}
        self._raise_for = raise_for or set()
        self.calls: list[tuple[bytes, FaceBox]] = []

    async def embed(self, image_bytes: bytes, face_box: FaceBox) -> Embedding:
        self.calls.append((image_bytes, face_box))
        if image_bytes in self._raise_for:
            raise RuntimeError("embed failed")
        return self._mapping.get(image_bytes, self._vector)


class StubVectorIndex:
    """Two modes: scripted search results (decision/dedupe tests) and real cosine
    search over upserted vectors (tenant-isolation/enrollment tests)."""

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], list[Embedding]] = {}
        self.upserts: list[tuple[str, str, list[Embedding], dict[str, object]]] = []
        self.deletes: list[tuple[str, str]] = []
        self.search_calls: list[tuple[str, int]] = []
        self._scripted: list[list[Candidate]] = []

    def script(self, *results_per_call: list[Candidate]) -> None:
        self._scripted = list(results_per_call)

    async def upsert(
        self,
        school_id: str,
        student_id: str,
        embeddings: list[Embedding],
        metadata: Mapping[str, object],
    ) -> None:
        self.store[(school_id, student_id)] = list(embeddings)
        self.upserts.append((school_id, student_id, list(embeddings), dict(metadata)))

    async def search(
        self, school_id: str, embedding: Embedding, top_k: int
    ) -> list[Candidate]:
        self.search_calls.append((school_id, top_k))
        if self._scripted:
            return self._scripted.pop(0)
        scored: list[Candidate] = []
        for (sch, student), embs in self.store.items():
            if sch != school_id:  # tenant isolation (NFR-3)
                continue
            best = max((_dot(embedding, e) for e in embs), default=None)
            if best is not None:
                scored.append(Candidate(student, best))
        scored.sort(key=lambda c: c.score, reverse=True)
        return scored[:top_k]

    async def delete(self, school_id: str, student_id: str) -> None:
        self.deletes.append((school_id, student_id))
        self.store.pop((school_id, student_id), None)


class StubMatchRepository:
    """In-memory repo mirroring the Postgres ON-CONFLICT-higher-wins rule."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], MatchRecord] = {}
        self.saved_batches: list[list[MatchRecord]] = []
        self.save_calls = 0

    async def save_batch(self, records: list[MatchRecord]) -> None:
        self.save_calls += 1
        self.saved_batches.append(list(records))
        for r in records:
            key = (r.media_id, r.student_id)
            existing = self.rows.get(key)
            if existing is None or r.confidence_score > existing.confidence_score:
                self.rows[key] = r

    async def exists(self, media_id: str, student_id: str) -> bool:
        return (media_id, student_id) in self.rows


class StubDetectionRepository:
    """In-memory DetectionRepository mirroring replace-by-media (last write wins)."""

    def __init__(self) -> None:
        self.by_media: dict[str, MediaDetectionRecord] = {}
        self.save_calls = 0

    async def save_detections(self, detection: MediaDetectionRecord) -> None:
        self.save_calls += 1
        self.by_media[detection.media_id] = detection


class StubBackendEventStore:
    """In-memory BackendEventStore: a fixed roster per (school_id, event_id), and it
    records the status writes the worker makes (decisions/0027)."""

    def __init__(self, roster: dict[tuple[str, str], list[BackendMedia]] | None = None) -> None:
        self._roster = roster or {}
        self.list_calls: list[tuple[str, str]] = []
        self.media_completed: list[str] = []
        self.media_failed: list[str] = []
        self.event_status: dict[str, str] = {}

    async def list_event_media(
        self, school_id: str, event_id: str
    ) -> list[BackendMedia]:
        self.list_calls.append((school_id, event_id))
        return list(self._roster.get((school_id, event_id), []))

    async def mark_media_completed(self, school_id: str, media_id: str) -> None:
        self.media_completed.append(media_id)

    async def mark_media_failed(self, school_id: str, media_id: str) -> None:
        self.media_failed.append(media_id)

    async def mark_event_processing(self, school_id: str, event_id: str) -> None:
        self.event_status[event_id] = "processing"

    async def mark_event_completed(self, school_id: str, event_id: str) -> None:
        self.event_status[event_id] = "completed"


class StubThresholdProvider:
    def __init__(self, match_confidence: float = 0.5, gap: float = 0.1) -> None:
        self._thresholds = Thresholds(match_confidence, gap)
        self.calls = 0

    async def get_thresholds(self, school_id: str) -> Thresholds:
        self.calls += 1
        return self._thresholds


class StubFrameExtractor:
    def __init__(self, frames: list[Frame]) -> None:
        self._frames = frames
        self.calls: list[tuple[int, float]] = []

    def extract(self, video_bytes: bytes, fps: float) -> Iterator[Frame]:
        self.calls.append((len(video_bytes), fps))
        return iter(self._frames)
