# 0016 — Phase 3: wiring (settings/registry/container) + API + worker

**Date:** 2026-07-03
**Status:** Accepted

## Context

Phase 1 delivered the pure `domain/` + `orchestration/`; Phase 2 delivered a real
adapter for every port. Phase 3 connects them: the composition root that turns
config into wired services, the synchronous enrollment API, and the async
inference worker loop. This is what makes NFR-1/NFR-2 (swap ML stack or storage
by config alone) real rather than aspirational.

## Decision

**Config surface (`wiring/settings.py`).** Extended `Settings` with the full req
§12 surface: decision defaults (`default_match_confidence_threshold=0.65`,
`default_gap_threshold=0.08`, `video_sample_fps=1.0`, `top_k=2`), the `*_impl`
adapter selectors, backing-store URLs (`ML_DATABASE_URL`, `ML_REDIS_URL`,
`ML_MODEL_DIR`, index-store dir, local media dir), Supabase credentials, the
Redis-Streams queue names, and worker retry knobs. All `ML_`-prefixed; secrets
(DB password, `ML_SUPABASE_KEY`) come from the environment only.

**Registry (`wiring/registry.py`).** A flat `name → "module:Class"` table per
port (architecture §8.1). `resolve()` imports lazily, so a Linux-only adapter
(insightface/decord) is only imported when actually selected — Windows dev and
CI stay importable. Unknown/malformed names raise `ConfigurationError` (fail loud).

**Container (`wiring/container.py`).** Reads each selector, resolves the class,
constructs it with impl-appropriate config, and **memoizes** it. Adapters are
built once and shared: models load a single time, the FAISS per-school cache and
the DB engine/sessionmaker are shared across both services. Lazy per-singleton
build means an API pod never constructs the queue and a worker never constructs
the reference-photo repo. Owns `check_readiness()` (pings only the infra this
deployment uses) and `aclose()`.

**API (`api/`).** `deps.py` exposes the process-wide container (memoized) and
builds the enrollment service off the event loop via a threadpool (models load on
first use). `routes/enrollment.py`: `POST /v1/schools/{sid}/students/{stid}/enroll`
(with `photo_uris` = enroll, without = refresh, per 0009) and
`DELETE …/{stid}` → 204. `routes/health.py` moves the probes out of `main.py`;
`/readyz` pings deps once the container is wired, and reports ready before wiring
(so `TestClient(app)` needs no backends). Domain errors are mapped centrally
(`EnrollmentError`→400, `MLServiceError`→500). The TEMP demo stays mounted until
Phase 4.

**Worker (`workers/`).** `runner.py::WorkerRunner` is the consume → process →
ack/nack loop: success acks (and deletes); `MediaDecodeError` acks (permanent,
no loop); `MediaFetchError` retries with exponential backoff then nacks;
any other error nacks (Redis `XAUTOCLAIM` redelivers, DLQ after max deliveries) —
architecture §8.4. Metrics go through a pluggable `on_outcome` sink (default logs
the req §13 `JobOutcome` fields + latency; Prometheus in Phase 4).
`inference_worker.py` is the real entrypoint (build container → build service in a
thread → run loop → dispose).

## Why

- **Selector + registry + container** is the smallest thing that satisfies
  NFR-1/NFR-2: adding S3/Milvus/SQS is a one-line registry entry plus a construct
  branch — `domain`/`orchestration` never change.
- **Lazy, memoized singletons** keep model loads to once, share the FAISS cache
  and DB pool, and let API and worker pods build only what they use.
- **Central error mapping + thin routes/loop** keep all logic in the services;
  the edges only translate transport concerns.

## Alternatives rejected

- **Generic `cls(**config)` injection for every port** — the adapters have
  genuinely different constructor shapes (`LocalFsMediaStore(base_dir)` vs
  `SupabaseMediaStore(url,key,bucket)`); explicit per-impl construction in the
  container is clearer and keeps the registry a pure name→class table.
- **Building the container in `lifespan` startup** — would load models at boot
  and make a bare `TestClient(app)` require a GPU/models; lazy build via `deps`
  keeps startup cheap and tests green.
- **Retry/DLQ logic in the worker** beyond backoff — delegated to the Redis
  adapter (`XAUTOCLAIM` + `max_deliveries`), which already owns redelivery; the
  runner only distinguishes permanent vs transient and acks/nacks.
