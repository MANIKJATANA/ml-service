"""Redis Streams ``JobQueue`` — the default async job queue (architecture §6, §8.4).

Uses a consumer group for at-least-once delivery, ``XAUTOCLAIM`` to recover jobs
stuck in a dead consumer's pending list, and a dead-letter stream for jobs that
exceed ``max_deliveries`` or arrive malformed. The lease ``receipt`` is the stream
message id; ``ack`` acknowledges + deletes it, ``nack`` leaves it pending so it is
reclaimed and redelivered.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from ml_service.domain.models import InferenceJob, JobLease, MediaType

_JOB_FIELDS = ("media_id", "media_uri", "school_id", "event_id", "media_type")


def _as_str(value: Any) -> str:
    return value.decode() if isinstance(value, (bytes, bytearray)) else str(value)


def _decode_fields(raw: dict[Any, Any]) -> dict[str, str]:
    return {_as_str(k): _as_str(v) for k, v in raw.items()}


class RedisStreamsJobQueue:
    """At-least-once job queue over a Redis stream + consumer group."""

    def __init__(
        self,
        client: Redis,
        *,
        stream: str,
        group: str,
        consumer: str,
        dead_letter_stream: str | None = None,
        max_deliveries: int = 5,
        block_ms: int = 5000,
        claim_min_idle_ms: int = 60000,
        claim_batch: int = 10,
    ) -> None:
        self._redis = client
        self._stream = stream
        self._group = group
        self._consumer = consumer
        self._dlq = dead_letter_stream or f"{stream}:dead"
        self._max_deliveries = max_deliveries
        self._block_ms = block_ms
        self._claim_min_idle_ms = claim_min_idle_ms
        self._claim_batch = claim_batch
        self._group_ready = False

    async def enqueue(self, job: InferenceJob) -> None:
        await self._redis.xadd(self._stream, cast("dict[Any, Any]", self._encode(job)))

    async def consume(self) -> AsyncIterator[JobLease]:
        await self._ensure_group()
        while True:
            for stuck in await self._reclaim_stuck():
                yield stuck
            resp: Any = await self._redis.xreadgroup(
                self._group,
                self._consumer,
                {self._stream: ">"},
                count=1,
                block=self._block_ms,
            )
            if not resp:
                continue
            for _stream_name, messages in resp:
                for msg_id, fields in messages:
                    lease = await self._to_lease(msg_id, fields)
                    if lease is not None:
                        yield lease

    async def ack(self, lease: JobLease) -> None:
        await self._redis.xack(self._stream, self._group, lease.receipt)
        await self._redis.xdel(self._stream, lease.receipt)

    async def nack(self, lease: JobLease) -> None:
        # Leave the message pending; XAUTOCLAIM redelivers it after the idle window
        # (and routes it to the dead-letter stream once max_deliveries is exceeded).
        return None

    # ---- internals ------------------------------------------------------

    async def _ensure_group(self) -> None:
        if self._group_ready:
            return
        try:
            await self._redis.xgroup_create(
                self._stream, self._group, id="0", mkstream=True
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        self._group_ready = True

    async def _reclaim_stuck(self) -> list[JobLease]:
        result = await self._redis.xautoclaim(
            self._stream,
            self._group,
            self._consumer,
            min_idle_time=self._claim_min_idle_ms,
            count=self._claim_batch,
        )
        messages = result[1] if len(result) > 1 else []
        leases: list[JobLease] = []
        for msg_id, fields in messages:
            if await self._delivery_count(msg_id) > self._max_deliveries:
                await self._to_dlq(msg_id, fields, reason="max_deliveries_exceeded")
                continue
            lease = await self._to_lease(msg_id, fields)
            if lease is not None:
                leases.append(lease)
        return leases

    async def _to_lease(self, msg_id: Any, fields: dict[Any, Any]) -> JobLease | None:
        job = self._decode(fields)
        if job is None:
            await self._to_dlq(msg_id, fields, reason="malformed")
            return None
        return JobLease(job=job, receipt=_as_str(msg_id))

    async def _delivery_count(self, msg_id: Any) -> int:
        pending = await self._redis.xpending_range(
            self._stream, self._group, min=_as_str(msg_id), max=_as_str(msg_id), count=1
        )
        if not pending:
            return 0
        return int(pending[0]["times_delivered"])

    async def _to_dlq(self, msg_id: Any, fields: dict[Any, Any], *, reason: str) -> None:
        payload = _decode_fields(fields)
        payload["_dlq_reason"] = reason
        payload["_orig_id"] = _as_str(msg_id)
        await self._redis.xadd(self._dlq, cast("dict[Any, Any]", payload))
        await self._redis.xack(self._stream, self._group, _as_str(msg_id))
        await self._redis.xdel(self._stream, _as_str(msg_id))

    @staticmethod
    def _encode(job: InferenceJob) -> dict[str, str]:
        return {
            "media_id": job.media_id,
            "media_uri": job.media_uri,
            "school_id": job.school_id,
            "event_id": job.event_id,
            "media_type": job.media_type.value,
        }

    @staticmethod
    def _decode(raw: dict[Any, Any]) -> InferenceJob | None:
        fields = _decode_fields(raw)
        if any(f not in fields for f in _JOB_FIELDS):
            return None
        try:
            media_type = MediaType(fields["media_type"])
        except ValueError:
            return None
        return InferenceJob(
            media_id=fields["media_id"],
            media_uri=fields["media_uri"],
            school_id=fields["school_id"],
            event_id=fields["event_id"],
            media_type=media_type,
        )
