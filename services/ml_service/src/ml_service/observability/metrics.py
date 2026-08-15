"""Prometheus metrics for the inference pipeline (requirements §13).

One aggregate sample set per finished job. Labels are **low-cardinality only** —
``school_id`` plus the detector/embedder model versions. Never label with
``student_id`` or ``media_id`` (unbounded → cardinality bomb, req §13 note).

:func:`record_job_outcome` has the :data:`ml_service.workers.runner.OutcomeSink`
signature, so the worker wires it straight in as an ``on_outcome`` callback; the
API exposes the default registry at ``/metrics`` (see :mod:`ml_service.api.main`).
"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from ml_service.domain.models import EventJob, EventOutcome

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
    "End-to-end event processing latency in milliseconds.",
    _LABELS,
    # Coarse buckets spanning a small event to a large one with long videos.
    buckets=(50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000, 300000),
)

# --- BP19b: the failure half of the pipeline (R3-S1-02) ---------------------
# These fire on the worker; the worker now exposes them at its own /metrics
# (workers/inference_worker.py), where they were previously recorded but unscraped.
PHOTOS_FAILED = Counter(
    "photos_failed_total", "Photos the worker couldn't process (per event).", _LABELS
)
JOBS_FAILED = Counter(
    "jobs_failed_total",
    "Event jobs that terminally failed (dead-lettered).",
    # `reason` is the queue's dead-letter cause — a small bounded set
    # (max_deliveries_exceeded / malformed / unknown), never an id.
    ("reason",),
)
EMBEDDING_VERSION_MISMATCH = Counter(
    "embedding_version_mismatch_total",
    # Fires per delivery ATTEMPT, not per distinct event: a stuck event is reclaimed +
    # retried up to max_deliveries (~5) times before dead-lettering, so it contributes ~5.
    # It's a mismatch-RATE alert signal (a rising rate ⇒ a stale index), not a job count.
    "Stale-index version-mismatch attempts — the 'ALERT' signal, now countable (per school).",
    ("school_id",),
)
# Both gauges are worker-observed over the ONE shared stream, so every replica reports the
# same value — aggregate across instances with max(), never sum() (like BP8c's per-replica note).
DLQ_DEPTH = Gauge(
    "dlq_depth", "Entries currently in the dead-letter stream (worker-observed; use max())."
)
INFLIGHT_OLDEST_AGE_MS = Gauge(
    "inflight_oldest_age_ms",
    "Age (ms) of the oldest in-flight (pending, unacked) job — 0 idle (worker-observed; max()).",
)


def record_job_outcome(job: EventJob, outcome: EventOutcome, latency_ms: float) -> None:
    """Fold one event's aggregate :class:`EventOutcome` into the counters/histogram.

    Metrics are event-grained now (one event job = many photos, decisions/0027); the
    counter surface is unchanged since ``EventOutcome`` sums the per-photo counters."""
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
    PHOTOS_FAILED.labels(**labels).inc(outcome.photos_failed)  # BP19b
    PROCESSING_LATENCY.labels(**labels).observe(latency_ms)


def record_job_failed(reason: str) -> None:
    """BP19b: a job terminally failed (dead-lettered). ``reason`` is the queue's cause."""
    JOBS_FAILED.labels(reason=reason).inc()


def record_version_mismatch(school_id: str) -> None:
    """BP19b: a stale-index version mismatch (the ALERT) — now a countable early signal."""
    EMBEDDING_VERSION_MISMATCH.labels(school_id=school_id).inc()


def set_queue_gauges(*, dlq_depth: int, oldest_pending_age_ms: float | None) -> None:
    """BP19b: refresh the worker-observed queue gauges each DLQ sweep. A ``None`` oldest age
    (an idle stream with nothing pending) reads as 0."""
    DLQ_DEPTH.set(dlq_depth)
    INFLIGHT_OLDEST_AGE_MS.set(oldest_pending_age_ms or 0.0)


def start_metrics_server(port: int) -> None:
    """Serve the default registry at ``/metrics`` on ``port`` in a daemon thread (BP19b).

    The inference **worker** has no HTTP server of its own, so its metrics (the job-outcome
    counters AND the new failure metrics) were recorded but never scraped. This exposes them;
    the API keeps serving its own registry at ``/metrics`` via :func:`render_latest`."""
    from prometheus_client import start_http_server

    start_http_server(port)


def render_latest() -> tuple[bytes, str]:
    """Return ``(body, content_type)`` for the ``/metrics`` scrape endpoint."""
    return generate_latest(), CONTENT_TYPE_LATEST
