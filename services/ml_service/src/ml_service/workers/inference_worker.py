"""Inference worker entrypoint — the real job loop.

Builds the composition-root container, constructs the inference service (loading
the detector/embedder models) and the job queue, then runs the consume loop
until interrupted. Model construction is offloaded to a thread so we don't block
the loop during startup; the container is disposed on exit.

Each replica must use a unique consumer name within the group for at-least-once
recovery — set ``ML_QUEUE_CONSUMER`` per replica in deployment.
"""

from __future__ import annotations

import asyncio
import logging

from ml_service.domain.models import EventJob, EventOutcome
from ml_service.observability import metrics
from ml_service.observability.logging import configure_logging
from ml_service.observability.tracing import configure_tracing
from ml_service.wiring.container import Container
from ml_service.wiring.settings import settings
from ml_service.workers.runner import WorkerRunner, log_outcome

log = logging.getLogger(__name__)


def _emit_outcome(job: EventJob, outcome: EventOutcome, latency_ms: float) -> None:
    """Fan a finished event job's outcome out to both structured logs and Prometheus."""
    log_outcome(job, outcome, latency_ms)
    metrics.record_job_outcome(job, outcome, latency_ms)


async def _run(container: Container) -> None:
    queue = container.job_queue()
    # Loading the models blocks — keep it off the loop during startup.
    service = await asyncio.to_thread(container.inference_service)
    runner = WorkerRunner(
        queue, service, on_outcome=_emit_outcome, dlq_poll_s=settings.dlq_poll_s
    )
    log.info(
        "inference worker starting",
        extra={"stream": settings.queue_stream, "consumer": settings.queue_consumer},
    )
    await runner.run()


async def _amain(container: Container) -> None:
    # Run and dispose on the SAME event loop — the async engine/Redis client are
    # bound to it, so cleanup must not happen under a second asyncio.run().
    try:
        await _run(container)
    finally:
        await container.aclose()


def main() -> None:
    configure_logging(settings.log_level, json_output=settings.log_json)
    configure_tracing(settings.service_name, otlp_endpoint=settings.otel_exporter_otlp_endpoint)
    # BP19b: the worker has no API of its own, so expose the default registry (job-outcome +
    # failure metrics) at its own /metrics. A bind failure (e.g. port already used by a second
    # worker on the same host) is logged but never kills the worker — metrics are not core.
    try:
        metrics.start_metrics_server(settings.worker_metrics_port)
        log.info("worker metrics server started", extra={"port": settings.worker_metrics_port})
    except OSError as exc:  # pragma: no cover - depends on host port availability
        log.warning(
            "worker metrics server failed to start; continuing without it",
            extra={"error": str(exc)},
        )
    container = Container(settings)
    try:
        asyncio.run(_amain(container))
    except KeyboardInterrupt:
        log.info("inference worker stopping")


if __name__ == "__main__":
    main()
