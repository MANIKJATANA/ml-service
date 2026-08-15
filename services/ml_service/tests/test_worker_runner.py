"""workers.runner: ack/nack semantics and the consume loop (event-level, 0027).

Delivery semantics are unit-tested via ``handle()`` with a recording queue and a
scripted service; the consume loop is exercised once against the real
``InProcJobQueue``. No models or network. Per-photo error handling lives in
``InferenceService.process_event`` (tested there); the runner is coarse — ack on
success, nack on failure.
"""

from __future__ import annotations

import asyncio
from typing import cast

import pytest
from ml_service.adapters.queue.inproc_queue import InProcJobQueue
from ml_service.domain.errors import EmbeddingVersionMismatch
from ml_service.domain.models import DeadLetter, EventJob, EventOutcome, JobLease
from ml_service.domain.ports import JobQueue
from ml_service.orchestration.inference import InferenceService
from ml_service.workers.runner import WorkerRunner

JOB = EventJob(school_id="school-1", event_id="ev-1")
OUTCOME = EventOutcome(
    photos_total=2,
    photos_processed=2,
    photos_skipped=0,
    photos_failed=0,
    faces_detected=3,
    candidates_above_threshold=3,
    matches_emitted=2,
    ambiguous_matches=0,
    unknown_faces=1,
    frames_processed=0,
    detector_version="det-1",
    embedding_model_version="emb-1",
)


class _RecordingQueue:
    def __init__(
        self,
        *,
        dead_letters: list[DeadLetter] | None = None,
        order: list[str] | None = None,
    ) -> None:
        self.acks: list[JobLease] = []
        self.nacks: list[JobLease] = []
        self._dead = list(dead_letters or [])
        self.removed: list[str] = []
        self._order = order

    async def ack(self, lease: JobLease) -> None:
        self.acks.append(lease)

    async def nack(self, lease: JobLease) -> None:
        self.nacks.append(lease)

    async def drain_dead_letters(self) -> list[DeadLetter]:
        # Returns the pending dead letters once; a subsequent drain sees nothing (they were
        # returned). The worker removes each via remove_dead_letter after marking.
        drained, self._dead = self._dead, []
        return drained

    async def remove_dead_letter(self, receipt: str) -> None:
        if self._order is not None:
            self._order.append(f"remove:{receipt}")
        self.removed.append(receipt)


class _ScriptedService:
    def __init__(
        self,
        *,
        outcome: EventOutcome | None = None,
        raises: Exception | None = None,
        order: list[str] | None = None,
    ):
        self.calls = 0
        self._outcome = outcome
        self._raises = raises
        self._order = order
        self.failed: list[EventJob] = []

    async def process_event(self, job: EventJob) -> EventOutcome:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        assert self._outcome is not None
        return self._outcome

    async def mark_event_failed(self, job: EventJob) -> None:
        if self._order is not None:
            self._order.append(f"mark:{job.event_id}")
        self.failed.append(job)


def _runner(queue: object, service: object, **kw: object) -> WorkerRunner:
    return WorkerRunner(
        cast(JobQueue, queue),
        cast(InferenceService, service),
        **kw,  # type: ignore[arg-type]
    )


def test_success_acks_and_emits_outcome() -> None:
    q = _RecordingQueue()
    svc = _ScriptedService(outcome=OUTCOME)
    seen: list[tuple[EventJob, EventOutcome, float]] = []
    runner = _runner(q, svc, on_outcome=lambda j, o, ms: seen.append((j, o, ms)))
    asyncio.run(runner.handle(JobLease(JOB, "r1")))
    assert len(q.acks) == 1 and not q.nacks
    assert seen and seen[0][1] is OUTCOME


def test_version_mismatch_nacks() -> None:
    q = _RecordingQueue()
    svc = _ScriptedService(raises=EmbeddingVersionMismatch("stale index"))
    asyncio.run(_runner(q, svc).handle(JobLease(JOB, "r1")))
    assert not q.acks and len(q.nacks) == 1
    assert svc.calls == 1  # systemic — surfaces via redelivery/DLQ + alert


def test_unexpected_error_nacks() -> None:
    q = _RecordingQueue()
    svc = _ScriptedService(raises=RuntimeError("roster read failed"))
    asyncio.run(_runner(q, svc).handle(JobLease(JOB, "r1")))
    assert not q.acks and len(q.nacks) == 1
    assert svc.calls == 1


def test_dlq_consumer_marks_event_failed_then_removes() -> None:
    # BP19a: the DLQ consumer that was missing. A dead-lettered job flips its event to
    # `failed` and is then removed — mark BEFORE remove, so a crash between the two re-marks
    # idempotently on the next drain (never loses the failure).
    order: list[str] = []
    dl = DeadLetter(job=JOB, reason="max_deliveries_exceeded", receipt="42-0")
    q = _RecordingQueue(dead_letters=[dl], order=order)
    svc = _ScriptedService(outcome=OUTCOME, order=order)
    asyncio.run(_runner(q, svc)._drain_dead_letters_once())
    assert svc.failed == [JOB]
    assert q.removed == ["42-0"]
    assert order == ["mark:ev-1", "remove:42-0"]  # mark strictly before remove


def test_dlq_drain_is_a_noop_when_empty() -> None:
    # A second drain (nothing left) marks/removes nothing — no re-processing of drained jobs.
    q = _RecordingQueue(dead_letters=[DeadLetter(JOB, "malformed", "9-0")])
    svc = _ScriptedService(outcome=OUTCOME)
    asyncio.run(_runner(q, svc)._drain_dead_letters_once())
    asyncio.run(_runner(q, svc)._drain_dead_letters_once())  # nothing left to drain
    assert svc.failed == [JOB] and q.removed == ["9-0"]


def test_run_loop_consumes_from_inproc_queue() -> None:
    async def drive() -> int:
        q = InProcJobQueue()
        svc = _ScriptedService(outcome=OUTCOME)
        seen: list[EventOutcome] = []
        runner = _runner(q, svc, on_outcome=lambda j, o, ms: seen.append(o))
        await q.enqueue(JOB)
        task = asyncio.create_task(runner.run())
        for _ in range(200):
            if seen:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return len(seen)

    assert asyncio.run(drive()) == 1
