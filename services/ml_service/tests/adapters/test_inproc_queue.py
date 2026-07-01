"""In-process JobQueue lease/ack/nack behaviour."""

from __future__ import annotations

from ml_service.adapters.queue.inproc_queue import InProcJobQueue
from ml_service.domain.models import InferenceJob, MediaType

JOB = InferenceJob(
    media_id="m1",
    media_uri="uri",
    school_id="s1",
    event_id="e1",
    media_type=MediaType.IMAGE,
)


async def test_enqueue_consume_ack() -> None:
    q = InProcJobQueue()
    await q.enqueue(JOB)
    stream = q.consume()
    lease = await anext(stream)
    assert lease.job == JOB
    await q.ack(lease)


async def test_nack_redelivers() -> None:
    q = InProcJobQueue()
    await q.enqueue(JOB)
    stream = q.consume()
    first = await anext(stream)
    await q.nack(first)
    second = await anext(stream)
    assert second.job == JOB
    assert second.receipt != first.receipt
