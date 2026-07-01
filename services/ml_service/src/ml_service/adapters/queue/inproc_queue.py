"""In-process ``JobQueue`` backed by a real ``asyncio.Queue`` — for single-process
runs and tests (architecture §5). Not a mock: it implements the full lease/ack/nack
contract; ``nack`` re-enqueues the job for redelivery (at-least-once)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from ml_service.domain.models import InferenceJob, JobLease


class InProcJobQueue:
    """A single-process at-least-once queue."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[InferenceJob] = asyncio.Queue()
        self._counter = 0

    async def enqueue(self, job: InferenceJob) -> None:
        await self._queue.put(job)

    async def consume(self) -> AsyncIterator[JobLease]:
        while True:
            job = await self._queue.get()
            self._counter += 1
            yield JobLease(job=job, receipt=str(self._counter))

    async def ack(self, lease: JobLease) -> None:
        self._queue.task_done()

    async def nack(self, lease: JobLease) -> None:
        self._queue.task_done()
        await self._queue.put(lease.job)  # redeliver
