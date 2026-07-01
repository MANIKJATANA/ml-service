"""Domain value objects — pure, no third-party imports.

Locked conventions (architecture §6): 512-dim ArcFace embeddings, L2-normalized,
compared by cosine similarity (inner product on normalized vectors).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

EMBEDDING_DIM = 512
SIMILARITY_METRIC = "cosine"


class MediaType(StrEnum):
    """Kind of media an inference job processes."""

    IMAGE = "image"
    VIDEO = "video"


class PhotoStatus(StrEnum):
    """Per-photo outcome of an enrollment request (FR-E4)."""

    ENROLLED = "enrolled"
    NO_FACE = "no_face"
    MULTIPLE_FACES = "multiple_faces"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class FaceBox:
    """A detected face's bounding box in pixel coordinates, with detector score.

    ``landmarks`` carries the detector's 5-point facial landmarks (both eyes,
    nose, mouth corners) when available. They ride inside ``FaceBox`` because the
    ``FaceEmbedder.embed(image_bytes, face_box)`` port passes only the box, yet
    ArcFace needs the landmarks to align the crop (see decisions/0013). Pure data
    — no third-party types; the embedder adapter converts to its own array form.
    """

    x1: float
    y1: float
    x2: float
    y2: float
    score: float
    landmarks: tuple[tuple[float, float], ...] | None = None

    @property
    def area(self) -> float:
        """Box area; used to pick the largest face (req §8.7)."""
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)


@dataclass(frozen=True, slots=True)
class Embedding:
    """An L2-normalized face embedding of fixed dimension ``EMBEDDING_DIM``."""

    vector: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.vector) != EMBEDDING_DIM:
            raise ValueError(
                f"Embedding must have {EMBEDDING_DIM} dimensions, "
                f"got {len(self.vector)}"
            )


@dataclass(frozen=True, slots=True)
class Candidate:
    """A vector-index search hit: a student and the similarity score."""

    student_id: str
    score: float


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Resolved per-school decision thresholds (req §6.1)."""

    match_confidence: float
    gap: float

    def clears(self, score: float) -> bool:
        """True if ``score`` meets the match-confidence threshold."""
        return score >= self.match_confidence


@dataclass(frozen=True, slots=True)
class Frame:
    """One image to run detection on. ``timestamp_ms`` is set only for video."""

    image_bytes: bytes
    timestamp_ms: int | None = None


@dataclass(frozen=True, slots=True)
class InferenceJob:
    """An inference job payload (req §10.3)."""

    media_id: str
    media_uri: str
    school_id: str
    event_id: str
    media_type: MediaType


@dataclass(frozen=True, slots=True)
class MatchRecord:
    """A match to persist (req §10.1).

    Versions and thresholds are the values used at decision time (NFR-4).
    ``match_id`` and ``created_at`` are assigned by the database.
    """

    school_id: str
    event_id: str
    student_id: str
    media_id: str
    media_type: MediaType
    confidence_score: float
    needs_review: bool
    embedding_model_version: str
    detector_model_version: str
    threshold_used: float
    gap_threshold_used: float
    bbox: FaceBox | None = None
    frame_timestamp_ms: int | None = None


@dataclass(frozen=True, slots=True)
class PhotoResult:
    """Per-photo status within an enrollment response (FR-E4)."""

    index: int
    status: PhotoStatus
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class EnrollmentResult:
    """Outcome of an enrollment request."""

    school_id: str
    student_id: str
    embeddings_stored: int
    photo_results: tuple[PhotoResult, ...]


@dataclass(frozen=True, slots=True)
class Emission:
    """A decision-function output: a candidate to emit and its review flag."""

    candidate: Candidate
    needs_review: bool


@dataclass(frozen=True, slots=True)
class JobLease:
    """A consumed job plus an opaque receipt used to ack/nack it."""

    job: InferenceJob
    receipt: str


@dataclass(frozen=True, slots=True)
class JobOutcome:
    """Per-job metrics returned by the inference service (req §13)."""

    faces_detected: int
    candidates_above_threshold: int
    matches_emitted: int
    ambiguous_matches: int
    unknown_faces: int
    frames_processed: int
    detector_version: str
    embedding_model_version: str
