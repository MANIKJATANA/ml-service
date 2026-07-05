"""workers.runner: ack/nack + retry semantics and the consume loop.

Delivery semantics are unit-tested via ``handle()`` with a recording queue and a
scripted service; the consume loop is exercised once against the real
``InProcJobQueue``. No models or network.
"""

from __future__ import annotations

import asyncio
from typing import cast

import pytest
from ml_service.adapters.queue.inproc_queue import InProcJobQueue
from ml_service.domain.errors import (
    EmbeddingVersionMismatch,
    MediaDecodeError,
    MediaFetchError,
)
from ml_service.domain.models import InferenceJob, JobLease, JobOutcome, MediaType
from ml_service.domain.ports import JobQueue
from ml_service.orchestration.inference import InferenceService
from ml_service.workers.runner import WorkerRunner

JOB = InferenceJob("m1", "s3://m1.jpg", "school-1", "ev-1", MediaType.IMAGE)
OUTCOME = JobOutcome(
    faces_detected=1,
    candidates_above_threshold=1,
    matches_emitted=1,
    ambiguous_matches=0,
    unknown_faces=0,
    frames_processed=1,
    detector_version="det-1",
    embedding_model_version="emb-1",
)


class _RecordingQueue:
    def __init__(self) -> None:
        self.acks: list[JobLease] = []
        self.nacks: list[JobLease] = []

    async def ack(self, lease: JobLease) -> None:
        self.acks.append(lease)

    async def nack(self, lease: JobLease) -> None:
        self.nacks.append(lease)


class _ScriptedService:
    def __init__(self, *, outcome: JobOutcome | None = None, raises: Exception | None = None):
        self.calls = 0
        self._outcome = outcome
        self._raises = raises

    async def process(self, job: InferenceJob) -> JobOutcome:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        assert self._outcome is not None
        return self._outcome


def _runner(queue: object, service: object, **kw: object) -> WorkerRunner:
    return WorkerRunner(
        cast(JobQueue, queue),
        cast(InferenceService, service),
        backoff_base_s=0.0,
        **kw,  # type: ignore[arg-type]
    )


def test_success_acks_and_emits_outcome() -> None:
    q = _RecordingQueue()
    svc = _ScriptedService(outcome=OUTCOME)
    seen: list[tuple[InferenceJob, JobOutcome, float]] = []
    runner = _runner(q, svc, on_outcome=lambda j, o, ms: seen.append((j, o, ms)))
    asyncio.run(runner.handle(JobLease(JOB, "r1")))
    assert len(q.acks) == 1 and not q.nacks
    assert seen and seen[0][1] is OUTCOME


def test_undecodable_media_acks_without_looping() -> None:
    q = _RecordingQueue()
    svc = _ScriptedService(raises=MediaDecodeError("corrupt"))
    asyncio.run(_runner(q, svc).handle(JobLease(JOB, "r1")))
    assert len(q.acks) == 1 and not q.nacks
    assert svc.calls == 1  # permanent — no retry


def test_transient_fetch_retries_then_nacks() -> None:
    q = _RecordingQueue()
    svc = _ScriptedService(raises=MediaFetchError("timeout"))
    asyncio.run(_runner(q, svc, max_retries=2).handle(JobLease(JOB, "r1")))
    assert not q.acks and len(q.nacks) == 1
    assert svc.calls == 3  # initial + 2 retries


def test_unexpected_error_nacks() -> None:
    q = _RecordingQueue()
    svc = _ScriptedService(raises=RuntimeError("boom"))
    asyncio.run(_runner(q, svc).handle(JobLease(JOB, "r1")))
    assert not q.acks and len(q.nacks) == 1
    assert svc.calls == 1


def test_version_mismatch_nacks_without_retry() -> None:
    q = _RecordingQueue()
    svc = _ScriptedService(raises=EmbeddingVersionMismatch("stale index"))
    asyncio.run(_runner(q, svc, max_retries=3).handle(JobLease(JOB, "r1")))
    assert not q.acks and len(q.nacks) == 1
    assert svc.calls == 1  # systemic — not retried like a transient fetch


def test_run_loop_consumes_from_inproc_queue() -> None:
    async def drive() -> int:
        q = InProcJobQueue()
        svc = _ScriptedService(outcome=OUTCOME)
        seen: list[JobOutcome] = []
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
