"""Prometheus metrics for the inference pipeline (requirements §13).

One aggregate sample set per finished job. Labels are **low-cardinality only** —
``school_id`` plus the detector/embedder model versions. Never label with
``student_id`` or ``media_id`` (unbounded → cardinality bomb, req §13 note).

:func:`record_job_outcome` has the :data:`ml_service.workers.runner.OutcomeSink`
signature, so the worker wires it straight in as an ``on_outcome`` callback; the
API exposes the default registry at ``/metrics`` (see :mod:`ml_service.api.main`).
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from ml_service.domain.models import InferenceJob, JobOutcome

# school_id is bounded per deployment; model versions change only on redeploy.
_LABELS = ("school_id", "detector_model_version", "embedding_model_version")

FACES_DETECTED = Counter(
    "faces_detected_total", "Faces detected across a job's media/frames.", _LABELS
)
CANDIDATES_ABOVE_THRESHOLD = Counter(
    "candidates_above_threshold_total", "Search candidates at or above threshold.", _LABELS
)
MATCHES_EMITTED = Counter(
    "matches_emitted_total", "Match records persisted for a job.", _LABELS
)
AMBIGUOUS_MATCHES = Counter(
    "ambiguous_matches_total", "Matches emitted with needs_review=true.", _LABELS
)
UNKNOWN_FACES = Counter(
    "unknown_faces_total", "Faces with no candidate above threshold.", _LABELS
)
FRAMES_PROCESSED = Counter(
    "frames_processed_total", "Video frames processed (0 for images).", _LABELS
)
PROCESSING_LATENCY = Histogram(
    "processing_latency_ms",
    "End-to-end job processing latency in milliseconds.",
    _LABELS,
    # Coarse buckets spanning a fast image (~tens of ms) to a long video job.
    buckets=(50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000),
)


def record_job_outcome(job: InferenceJob, outcome: JobOutcome, latency_ms: float) -> None:
    """Fold one :class:`JobOutcome` into the Prometheus counters/histogram."""
    labels = {
        "school_id": job.school_id,
        "detector_model_version": outcome.detector_version,
        "embedding_model_version": outcome.embedding_model_version,
    }
    FACES_DETECTED.labels(**labels).inc(outcome.faces_detected)
    CANDIDATES_ABOVE_THRESHOLD.labels(**labels).inc(outcome.candidates_above_threshold)
    MATCHES_EMITTED.labels(**labels).inc(outcome.matches_emitted)
    AMBIGUOUS_MATCHES.labels(**labels).inc(outcome.ambiguous_matches)
    UNKNOWN_FACES.labels(**labels).inc(outcome.unknown_faces)
    FRAMES_PROCESSED.labels(**labels).inc(outcome.frames_processed)
    PROCESSING_LATENCY.labels(**labels).observe(latency_ms)


def render_latest() -> tuple[bytes, str]:
    """Return ``(body, content_type)`` for the ``/metrics`` scrape endpoint."""
    return generate_latest(), CONTENT_TYPE_LATEST
