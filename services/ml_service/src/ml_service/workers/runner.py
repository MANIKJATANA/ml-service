"""Inference worker loop — consume → process → ack/nack (architecture §3, §8.4).

Thin shell over :class:`InferenceService`: it owns delivery semantics only. Per
job it resolves nothing itself (the service snapshots thresholds/versions),
emits the returned :class:`JobOutcome` as metrics, and drives at-least-once
acking:

* success                → ``ack`` (and delete from the stream)
* corrupt/undecodable     → ``ack`` — permanent, don't loop (§8.4)
* transient fetch failure → retry with backoff, then ``nack`` for redelivery
* any other failure       → ``nack`` (redelivered; DLQ'd after max deliveries)

Metrics are emitted via an injectable ``on_outcome`` callback (Phase 4 wires
Prometheus); the default logs a structured record. The DB unique constraint on
``(media_id, student_id)`` makes redelivery idempotent (NFR-5).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from ml_service.domain.errors import (
    EmbeddingVersionMismatch,
    MediaDecodeError,
    MediaFetchError,
)
from ml_service.domain.models import InferenceJob, JobLease, JobOutcome
from ml_service.domain.ports import JobQueue
from ml_service.observability.tracing import span
from ml_service.orchestration.inference import InferenceService

log = logging.getLogger(__name__)

OutcomeSink = Callable[[InferenceJob, JobOutcome, float], None]


def log_outcome(job: InferenceJob, outcome: JobOutcome, latency_ms: float) -> None:
    log.info(
        "inference job complete",
        extra={
            "school_id": job.school_id,
            "event_id": job.event_id,
            "media_id": job.media_id,
            "media_type": job.media_type.value,
            "faces_detected": outcome.faces_detected,
            "candidates_above_threshold": outcome.candidates_above_threshold,
            "matches_emitted": outcome.matches_emitted,
            "ambiguous_matches": outcome.ambiguous_matches,
            "unknown_faces": outcome.unknown_faces,
            "frames_processed": outcome.frames_processed,
            "processing_latency_ms": round(latency_ms, 1),
            "detector_model_version": outcome.detector_version,
            "embedding_model_version": outcome.embedding_model_version,
        },
    )


class WorkerRunner:
    """Drives one consumer over a ``JobQueue`` through an ``InferenceService``."""

    def __init__(
        self,
        queue: JobQueue,
        service: InferenceService,
        *,
        max_retries: int = 3,
        backoff_base_s: float = 0.5,
        on_outcome: OutcomeSink = log_outcome,
    ) -> None:
        self._queue = queue
        self._service = service
        self._max_retries = max_retries
        self._backoff_base_s = backoff_base_s
        self._on_outcome = on_outcome

    async def run(self) -> None:
        """Consume and process jobs until cancelled.

        A failure in ``handle`` (including a transient ack/nack error from the
        queue) is logged and the loop continues, so one bad job or infra hiccup
        never kills the consumer. Cancellation (``CancelledError``, a
        ``BaseException``) still propagates and stops the loop cleanly.
        """
        async for lease in self._queue.consume():
            try:
                await self.handle(lease)
            except Exception:
                log.exception(
                    "unrecoverable error handling lease; continuing",
                    extra={"media_id": lease.job.media_id},
                )

    async def handle(self, lease: JobLease) -> None:
        """Process one leased job with retry/ack/nack (public for tests)."""
        job = lease.job
        attempt = 0
        while True:
            started = time.perf_counter()
            try:
                with span(
                    "inference.process",
                    school_id=job.school_id,
                    media_id=job.media_id,
                    media_type=job.media_type.value,
                    attempt=attempt,
                ):
                    outcome = await self._service.process(job)
            except MediaDecodeError as exc:
                # Permanent — a corrupt media item; mark complete, never loop.
                log.warning(
                    "undecodable media; marking job complete",
                    extra={"media_id": job.media_id, "reason": str(exc)},
                )
                await self._queue.ack(lease)
                return
            except MediaFetchError:
                attempt += 1
                if attempt > self._max_retries:
                    log.error(
                        "media fetch failed after retries; nacking",
                        extra={"media_id": job.media_id, "attempts": attempt},
                    )
                    await self._queue.nack(lease)
                    return
                await asyncio.sleep(self._backoff_base_s * 2 ** (attempt - 1))
                continue
            except EmbeddingVersionMismatch:
                # Systemic config error, not per-job: the index is stale vs the
                # configured embedder (§7.3/§8.4 "fail loud, alert"). Nack so it
                # surfaces via redelivery/DLQ rather than being silently dropped.
                log.error(
                    "embedding-model version mismatch; index is stale — ALERT",
                    extra={"media_id": job.media_id, "school_id": job.school_id},
                )
                await self._queue.nack(lease)
                return
            except Exception:
                log.exception("job failed; nacking", extra={"media_id": job.media_id})
                await self._queue.nack(lease)
                return
            latency_ms = (time.perf_counter() - started) * 1000.0
            await self._queue.ack(lease)
            self._on_outcome(job, outcome, latency_ms)
            return
