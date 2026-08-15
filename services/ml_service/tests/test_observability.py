"""observability: metric recording, the /metrics endpoint, and log/trace setup.

CPU-only, no backends: exercises the Prometheus counters (via a unique label so
the assertion is independent of other tests), the render helper, the scrape
endpoint, and that logging/tracing configuration is side-effect-safe to call.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace

from fastapi.testclient import TestClient
from ml_service.api.main import app
from ml_service.domain.models import EventJob, EventOutcome
from ml_service.observability import metrics
from ml_service.observability.logging import configure_logging, get_logger
from ml_service.observability.tracing import configure_tracing, span

_JOB = EventJob(school_id="school-obs", event_id="ev-1")
_OUTCOME = EventOutcome(
    photos_total=2,
    photos_processed=2,
    photos_skipped=0,
    photos_failed=0,
    faces_detected=3,
    candidates_above_threshold=2,
    matches_emitted=2,
    ambiguous_matches=1,
    unknown_faces=1,
    frames_processed=0,
    detector_version="det-obs",
    embedding_model_version="emb-obs",
)


def _counter_value(counter: object, **labels: str) -> float:
    return float(counter.labels(**labels)._value.get())  # type: ignore[attr-defined]


def test_record_job_outcome_increments_counters() -> None:
    labels = dict(
        school_id="school-obs",
        detector_model_version="det-obs",
        embedding_model_version="emb-obs",
    )
    before = _counter_value(metrics.FACES_DETECTED, **labels)
    metrics.record_job_outcome(_JOB, _OUTCOME, latency_ms=12.5)
    after = _counter_value(metrics.FACES_DETECTED, **labels)
    assert after - before == 3
    assert _counter_value(metrics.MATCHES_EMITTED, **labels) >= 2


def test_bp19b_failure_metrics_increment() -> None:
    # BP19b: the failure half of the pipeline now emits metrics (was zero).
    before_jobs = _counter_value(metrics.JOBS_FAILED, reason="max_deliveries_exceeded")
    metrics.record_job_failed("max_deliveries_exceeded")
    assert (
        _counter_value(metrics.JOBS_FAILED, reason="max_deliveries_exceeded")
        - before_jobs
        == 1
    )

    before_vm = _counter_value(metrics.EMBEDDING_VERSION_MISMATCH, school_id="school-vm")
    metrics.record_version_mismatch("school-vm")
    assert (
        _counter_value(metrics.EMBEDDING_VERSION_MISMATCH, school_id="school-vm")
        - before_vm
        == 1
    )


def test_bp19b_photos_failed_counter_from_outcome() -> None:
    labels = dict(
        school_id="school-pf",
        detector_model_version="det-pf",
        embedding_model_version="emb-pf",
    )
    outcome = replace(
        _OUTCOME, photos_failed=2, detector_version="det-pf", embedding_model_version="emb-pf"
    )
    before = _counter_value(metrics.PHOTOS_FAILED, **labels)
    metrics.record_job_outcome(EventJob(school_id="school-pf", event_id="e"), outcome, 1.0)
    assert _counter_value(metrics.PHOTOS_FAILED, **labels) - before == 2


def test_bp19b_queue_gauges_set() -> None:
    metrics.set_queue_gauges(dlq_depth=7, oldest_pending_age_ms=4200.0)
    assert metrics.DLQ_DEPTH._value.get() == 7
    assert metrics.INFLIGHT_OLDEST_AGE_MS._value.get() == 4200.0
    # A `None` oldest age (idle stream, nothing pending) reads as 0.
    metrics.set_queue_gauges(dlq_depth=0, oldest_pending_age_ms=None)
    assert metrics.DLQ_DEPTH._value.get() == 0
    assert metrics.INFLIGHT_OLDEST_AGE_MS._value.get() == 0.0


def test_render_latest_exposes_metric_names() -> None:
    metrics.record_job_outcome(_JOB, _OUTCOME, latency_ms=5.0)
    metrics.record_job_failed("max_deliveries_exceeded")
    metrics.set_queue_gauges(dlq_depth=1, oldest_pending_age_ms=1.0)
    body, content_type = metrics.render_latest()
    text = body.decode()
    assert "faces_detected_total" in text
    assert "processing_latency_ms" in text
    # BP19b failure metrics are exposed too.
    assert "jobs_failed_total" in text
    assert "photos_failed_total" in text
    assert "dlq_depth" in text
    assert "inflight_oldest_age_ms" in text
    assert content_type.startswith("text/plain")


def test_metrics_endpoint_scrapes() -> None:
    # No context manager -> lifespan/container not built; the route needs neither.
    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "matches_emitted_total" in resp.text


def test_logging_and_tracing_setup_are_safe() -> None:
    configure_logging("INFO", json_output=True)
    get_logger("test").info("structured log line", key="value")
    # No endpoint -> tracing stays a no-op; span() must still be usable.
    configure_tracing("ml-service-test", otlp_endpoint="")
    with span("unit.span", school_id="school-obs"):
        pass


def test_stdlib_extra_fields_survive_the_bridge(capsys: object) -> None:
    # The worker logs its JobOutcome via stdlib logging with extra={...}. Guard
    # that those fields reach the rendered JSON (the ExtraAdder bridge), since a
    # regression there silently guts the structured worker logs.
    configure_logging("INFO", json_output=True)
    logging.getLogger("ml_service.test").info(
        "inference job complete", extra={"school_id": "s-bridge", "faces_detected": 7}
    )
    out = capsys.readouterr().out.strip().splitlines()  # type: ignore[attr-defined]
    record = json.loads(out[-1])
    assert record["event"] == "inference job complete"
    assert record["school_id"] == "s-bridge"
    assert record["faces_detected"] == 7
