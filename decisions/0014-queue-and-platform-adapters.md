# 0014 — Redis Streams queue + in-proc queue; Linux-only heavy deps

**Date:** 2026-07-02
**Status:** Accepted

## Context

Phase 2 implements the `JobQueue` and the video extractor, and adds the heavy ML
deps. Two of those deps (`insightface`, `decord`) have no prebuilt Windows/py312
wheels, but local dev is on Windows while deployment is Linux Docker.

## Decision

- **`RedisStreamsJobQueue`** is the default `JobQueue` (architecture §6, §8.4):
  a consumer group for at-least-once delivery, `XAUTOCLAIM` to recover jobs stuck
  in a dead consumer's pending list, and a dead-letter stream for malformed jobs
  or those exceeding `max_deliveries`. The lease `receipt` is the stream message
  id; `ack` = `XACK` + `XDEL`; `nack` leaves the message pending for reclaim.
- **`InProcJobQueue`** (a real `asyncio.Queue`) is the single-process/test
  adapter — full lease/ack/nack, `nack` redelivers. Not a mock.
- **Video:** `DecordFrameExtractor` is the default (fast); `OpenCvFrameExtractor`
  is the cross-platform fallback and the dev default on Windows. Both yield each
  sampled frame as **encoded bytes** so the detector's `detect(image_bytes)`
  contract holds, with a deterministic `frame_timestamp_ms`.
- **Dependency platform markers:** `insightface` and `decord` are declared
  `; sys_platform == 'linux'`. They install and run in the Docker image; local
  Windows dev relies on the OpenCV extractor and the import-gated tests
  (`pytest.importorskip`). All other heavy deps (faiss-cpu, onnxruntime,
  opencv-python-headless, supabase, sqlalchemy, asyncpg, alembic, redis) install
  cross-platform.

## Why

- Redis Streams gives durable at-least-once semantics and lag metrics for
  autoscaling (architecture §4); the in-proc queue keeps tests and single-process
  runs offline and fast.
- Platform markers keep `uv sync` working on Windows without abandoning the "real
  adapters, everything downloaded" goal — the full stack is present in Docker.

## Alternatives rejected

- **Making all heavy deps unconditional** — breaks `uv sync` on the owner's
  Windows dev machine (no insightface/decord wheels).
- **A mock queue in tests** — the in-proc queue is a real asyncio implementation,
  consistent with the "no fakes in runnable paths" rule.
