"""Redis Streams JobQueue against a real Redis.

Set ``ML_TEST_REDIS_URL`` (redis://...) to run; otherwise skipped.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio

redis_asyncio = pytest.importorskip("redis.asyncio")

from ml_service.adapters.queue.redis_streams import RedisStreamsJobQueue  # noqa: E402
from ml_service.domain.models import EventJob  # noqa: E402

URL = os.environ.get("ML_TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(not URL, reason="ML_TEST_REDIS_URL not set")

JOB = EventJob(school_id="s1", event_id="e1")


@pytest_asyncio.fixture
async def client():  # type: ignore[no-untyped-def]
    c = redis_asyncio.from_url(URL)
    # isolate: fresh stream per run
    await c.delete("ml:test:jobs", "ml:test:jobs:dead")
    yield c
    await c.delete("ml:test:jobs", "ml:test:jobs:dead")
    await c.aclose()


async def test_enqueue_consume_ack_roundtrip(client) -> None:  # type: ignore[no-untyped-def]
    q = RedisStreamsJobQueue(
        client, stream="ml:test:jobs", group="g1", consumer="c1"
    )
    await q.enqueue(JOB)
    stream = q.consume()
    lease = await anext(stream)
    assert lease.job == JOB
    await q.ack(lease)
    # after ack the stream entry is deleted
    assert await client.xlen("ml:test:jobs") == 0


async def test_drain_and_remove_dead_letters(client) -> None:  # type: ignore[no-untyped-def]
    # BP19a: the DLQ consumer's queue-side behavior against real Redis. drain_dead_letters
    # returns the actionable entries (reason + receipt) WITHOUT removing them (mark-before-
    # remove crash-safety), drops a malformed entry in place, and remove_dead_letter deletes
    # a drained entry.
    q = RedisStreamsJobQueue(client, stream="ml:test:jobs", group="g1", consumer="c1")
    dead = "ml:test:jobs:dead"
    await client.xadd(
        dead,
        {"school_id": "s1", "event_id": "e1", "_dlq_reason": "max_deliveries_exceeded"},
    )
    await client.xadd(dead, {"school_id": "s1", "_dlq_reason": "malformed"})  # no event_id

    drained = await q.drain_dead_letters()
    assert len(drained) == 1  # only the actionable one; the malformed is dropped
    assert drained[0].job == JOB
    assert drained[0].reason == "max_deliveries_exceeded"
    assert drained[0].receipt  # the stream id used to remove it
    # the malformed entry was removed in place; the actionable one persists until removed
    assert await client.xlen(dead) == 1

    await q.remove_dead_letter(drained[0].receipt)
    assert await client.xlen(dead) == 0
    assert await q.drain_dead_letters() == []  # a second drain is a no-op


async def test_queue_stats_gauges(client) -> None:  # type: ignore[no-untyped-def]
    # BP19b: the DLQ-depth + oldest-in-flight-age gauges read from real Redis.
    q = RedisStreamsJobQueue(client, stream="ml:test:jobs", group="g1", consumer="c1")
    # idle: nothing dead, nothing pending
    assert await q.dead_letter_depth() == 0
    assert await q.oldest_pending_age_ms() is None

    await client.xadd(
        "ml:test:jobs:dead", {"school_id": "s1", "event_id": "e1", "_dlq_reason": "x"}
    )
    assert await q.dead_letter_depth() == 1

    # a consumed-but-unacked job is "in flight" (pending) with a measurable age
    await q.enqueue(JOB)
    lease = await anext(q.consume())
    age = await q.oldest_pending_age_ms()
    assert age is not None and age >= 0
    await q.ack(lease)
    assert await q.oldest_pending_age_ms() is None  # acked -> no longer pending
