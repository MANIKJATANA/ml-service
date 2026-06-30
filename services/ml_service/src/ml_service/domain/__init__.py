"""Pure domain layer — imports NO third-party ML/IO libraries.

Holds the value-object models, the nine Protocol ports (requirements §9 plus
``ReferencePhotoRepository`` for the enroll-by-student-id contract, see
decisions/0009), the pure ``apply_threshold_and_gap`` decision function
(requirements §6.2), and the error hierarchy.

Locked conventions (architecture §6):
    EMBEDDING_DIM = 512          # ArcFace R100
    SIMILARITY_METRIC = "cosine" # L2-normalized -> inner product
"""

from ml_service.domain.decision import apply_threshold_and_gap
from ml_service.domain.errors import (
    ConfigurationError,
    EmbeddingVersionMismatch,
    EnrollmentError,
    InferenceError,
    MediaDecodeError,
    MediaFetchError,
    MLServiceError,
)
from ml_service.domain.models import (
    EMBEDDING_DIM,
    SIMILARITY_METRIC,
    Candidate,
    Embedding,
    Emission,
    EnrollmentResult,
    FaceBox,
    Frame,
    InferenceJob,
    JobLease,
    JobOutcome,
    MatchRecord,
    MediaType,
    PhotoResult,
    PhotoStatus,
    Thresholds,
)
from ml_service.domain.ports import (
    FaceDetector,
    FaceEmbedder,
    JobQueue,
    MatchRepository,
    MediaStore,
    ReferencePhotoRepository,
    ThresholdProvider,
    VectorIndex,
    VideoFrameExtractor,
)

__all__ = [
    "EMBEDDING_DIM",
    "SIMILARITY_METRIC",
    "Candidate",
    "ConfigurationError",
    "Embedding",
    "EmbeddingVersionMismatch",
    "Emission",
    "EnrollmentError",
    "EnrollmentResult",
    "FaceBox",
    "FaceDetector",
    "FaceEmbedder",
    "Frame",
    "InferenceError",
    "InferenceJob",
    "JobLease",
    "JobOutcome",
    "JobQueue",
    "MLServiceError",
    "MatchRecord",
    "MatchRepository",
    "MediaDecodeError",
    "MediaFetchError",
    "MediaStore",
    "MediaType",
    "PhotoResult",
    "PhotoStatus",
    "ReferencePhotoRepository",
    "ThresholdProvider",
    "Thresholds",
    "VectorIndex",
    "VideoFrameExtractor",
    "apply_threshold_and_gap",
]
