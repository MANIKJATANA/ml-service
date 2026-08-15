"""Redis Streams ``JobQueue`` — the default async job queue (architecture §6, §8.4).

Uses a consumer group for at-least-once delivery, ``XAUTOCLAIM`` to recover jobs
stuck in a dead consumer's pending list, and a dead-letter stream for jobs that
exceed ``max_deliveries`` or arrive malformed. The lease ``receipt`` is the stream
message id; ``ack`` acknowledges + deletes it, ``nack`` leaves it pending so it is
reclaimed and redelivered.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any, cast

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from ml_service.domain.models import DeadLetter, EventJob, JobLease

_JOB_FIELDS = ("school_id", "event_id")

# BP19a: cap how many dead-letter entries one drain sweep loads, so a mass dead-letter event
# (e.g. a persistent version mismatch DLQ'ing many schools) can't balloon a single sweep's
# memory/work. Any overflow is drained on the next sweep — bounded latency, bounded footprint.
_DLQ_DRAIN_MAX = 256


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

    async def enqueue(self, job: EventJob) -> None:
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

    async def drain_dead_letters(self) -> list[DeadLetter]:
        # BP19a: read the current dead-letter entries so the worker can flip each event to
        # `failed`. Actionable entries are returned (with their id) but NOT removed here — the
        # worker removes them only after marking (mark-before-remove). A malformed DLQ entry
        # names no event, so there's nothing to mark: drop it in place so it can't accumulate.
        entries: Any = await self._redis.xrange(self._dlq, count=_DLQ_DRAIN_MAX)
        drained: list[DeadLetter] = []
        for msg_id, fields in entries:
            job = self._decode(fields)
            if job is None:
                await self._redis.xdel(self._dlq, _as_str(msg_id))
                continue
            reason = _decode_fields(fields).get("_dlq_reason", "unknown")
            drained.append(
                DeadLetter(job=job, reason=reason, receipt=_as_str(msg_id))
            )
        return drained

    async def remove_dead_letter(self, receipt: str) -> None:
        await self._redis.xdel(self._dlq, receipt)

    async def dead_letter_depth(self) -> int:
        # BP19b: gauge — how many jobs are sitting dead in the DLQ right now.
        return int(await self._redis.xlen(self._dlq))

    async def oldest_pending_age_ms(self) -> float | None:
        # BP19b: gauge — age of the oldest in-flight (pending, unacked) job. Redis stream ids
        # are `<ms>-<seq>`, so the oldest pending id's ms prefix gives its enqueue time; the
        # age is now - that. None when nothing is pending (an idle stream).
        await self._ensure_group()
        summary: Any = await self._redis.xpending(self._stream, self._group)
        if not isinstance(summary, dict):
            return None
        oldest = summary.get("min")
        if not summary.get("pending") or oldest is None:
            return None
        try:
            enqueued_ms = int(_as_str(oldest).split("-")[0])
        except (ValueError, IndexError):
            return None
        return max(0.0, time.time() * 1000.0 - enqueued_ms)

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
    def _encode(job: EventJob) -> dict[str, str]:
        return {"school_id": job.school_id, "event_id": job.event_id}

    @staticmethod
    def _decode(raw: dict[Any, Any]) -> EventJob | None:
        fields = _decode_fields(raw)
        if any(f not in fields for f in _JOB_FIELDS):
            return None
        return EventJob(school_id=fields["school_id"], event_id=fields["event_id"])
