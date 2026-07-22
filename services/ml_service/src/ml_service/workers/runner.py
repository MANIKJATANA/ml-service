"""Inference worker loop — consume → process event → ack/nack (architecture §3, §8.4).

Thin shell over :class:`InferenceService`: it owns delivery semantics only. Each queued
job is one **event** (decisions/0027); ``process_event`` reads the event's photo roster
and runs the pipeline per photo, handling per-photo errors internally (skip + let a
later redistribute retry). So the runner's job is coarse:

* success                     → ``ack`` (and delete from the stream)
* stale-index version mismatch → ``nack`` — systemic, surfaces via redelivery/DLQ + alert
* any other failure            → ``nack`` (redelivered; DLQ'd after max deliveries)

Metrics are emitted via an injectable ``on_outcome`` callback (Phase 4 wires Prometheus);
the default logs a structured record. Per-photo writes are idempotent (media_detections
replace-by-media; matches higher-confidence-wins), so redelivery is safe (NFR-5).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from ml_service.domain.errors import EmbeddingVersionMismatch
from ml_service.domain.models import EventJob, EventOutcome, JobLease
from ml_service.domain.ports import JobQueue
from ml_service.observability.tracing import span
from ml_service.orchestration.inference import InferenceService

log = logging.getLogger(__name__)

OutcomeSink = Callable[[EventJob, EventOutcome, float], None]


def log_outcome(job: EventJob, outcome: EventOutcome, latency_ms: float) -> None:
    log.info(
        "event inference complete",
        extra={
            "school_id": job.school_id,
            "event_id": job.event_id,
            "photos_total": outcome.photos_total,
            "photos_processed": outcome.photos_processed,
            "photos_skipped": outcome.photos_skipped,
            "photos_failed": outcome.photos_failed,
            "faces_detected": outcome.faces_detected,
            "matches_emitted": outcome.matches_emitted,
            "processing_latency_ms": round(latency_ms, 1),
        },
    )


class WorkerRunner:
    """Drives one consumer over a ``JobQueue`` through an ``InferenceService``."""

    def __init__(
        self,
        queue: JobQueue,
        service: InferenceService,
        *,
        on_outcome: OutcomeSink = log_outcome,
    ) -> None:
        self._queue = queue
        self._service = service
        self._on_outcome = on_outcome

    async def run(self) -> None:
        """Consume and process event jobs until cancelled.

        A failure in ``handle`` (including a transient ack/nack error from the queue) is
        logged and the loop continues, so one bad job or infra hiccup never kills the
        consumer. Cancellation (``CancelledError``, a ``BaseException``) still propagates
        and stops the loop cleanly.
        """
        async for lease in self._queue.consume():
            try:
                await self.handle(lease)
            except Exception:
                log.exception(
                    "unrecoverable error handling lease; continuing",
                    extra={"event_id": lease.job.event_id},
                )

    async def handle(self, lease: JobLease) -> None:
        """Process one leased event job with ack/nack (public for tests)."""
        job = lease.job
        started = time.perf_counter()
        try:
            with span(
                "inference.process_event",
                school_id=job.school_id,
                event_id=job.event_id,
            ):
                outcome = await self._service.process_event(job)
        except EmbeddingVersionMismatch:
            # Systemic config error, not per-job: the index is stale vs the configured
            # embedder (§7.3/§8.4 "fail loud, alert"). Nack so it surfaces via
            # redelivery/DLQ rather than being silently dropped.
            log.error(
                "embedding-model version mismatch; index is stale — ALERT",
                extra={"event_id": job.event_id, "school_id": job.school_id},
            )
            await self._queue.nack(lease)
            return
        except Exception:
            log.exception("event job failed; nacking", extra={"event_id": job.event_id})
            await self._queue.nack(lease)
            return
        latency_ms = (time.perf_counter() - started) * 1000.0
        await self._queue.ack(lease)
        self._on_outcome(job, outcome, latency_ms)
