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
