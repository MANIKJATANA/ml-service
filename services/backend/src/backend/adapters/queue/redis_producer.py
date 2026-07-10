"""Redis Streams event-job producer — the backend's enqueue side (decisions/0027).

XADDs one message per **event** onto the stream the ML inference worker consumes. The
field names are a **binding contract** with the ML worker (decisions/0022): exactly
``school_id, event_id``, both strings. The ML worker reads the backend ``media`` roster
for the event from the shared DB to learn which photos to process — so the job carries
no photo list. A renamed field makes the ML worker dead-letter the job as malformed, so
``encode_job`` is kept pure + unit-tested (the producer-contract test).

An unreachable/erroring Redis surfaces as ``UpstreamError`` → HTTP 502.
"""

from __future__ import annotations

from typing import Any, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from backend.domain.errors import UpstreamError
from backend.domain.models import EventJob

# Must match ml_service's event-job field tuple exactly (decisions/0022).
_JOB_FIELDS = ("school_id", "event_id")


def encode_job(job: EventJob) -> dict[str, str]:
    """The exact two string fields the ML worker decodes. Pure — the contract test
    asserts the key set."""
    return {"school_id": job.school_id, "event_id": job.event_id}


class RedisEventJobProducer:
    """``EventJobProducer`` over a Redis stream (``XADD``)."""

    def __init__(self, redis_url: str, *, stream: str) -> None:
        # A lazy client so construction never blocks — the first enqueue connects.
        self._redis: Redis = Redis.from_url(redis_url)
        self._stream = stream

    async def enqueue(self, job: EventJob) -> None:
        try:
            await self._redis.xadd(
                self._stream, cast("dict[Any, Any]", encode_job(job))
            )
        except (RedisError, OSError) as exc:
            raise UpstreamError(f"failed to enqueue event job: {exc}") from exc

    async def aclose(self) -> None:
        await self._redis.aclose()
