# 0052 — Product Build BP8d: Multi-replica enrollment (FAISS write lock, Option B / Redis)

**Date:** 2026-07-24
**Status:** Accepted

## Context

Fourth slice of **BP8 (Ops & reliability)** (`product/03`; after BP8a/b/c). Per
[decisions/0011](decisions/0011-faiss-adapter-lifecycle.md) + architecture §7.4, enrollment serializes each school's
FAISS index writes with an in-process `asyncio.Lock` (**Option A**) — the fleet-wide lock **only because enrollment
runs single-replica** ("the process is the lock"). That's a SPOF/bottleneck (fails lens **X5/T7**). **Option B** = a
per-school **Redis distributed lock** so enrollment can scale to multiple replicas without two of them
read-modify-writing the same school's index and clobbering an enrollment. Reads were **already** cross-replica-safe (the
read path re-checks `meta.version` and reloads on staleness). **ML-service only; no migration, no backend/FE change, no
ML-contract change; config-gated (Option A stays the default).** 0011 promised "the migration to B is trivial — the same
adapter code path"; this is that.

## Decisions

### 1. A pluggable write-lock provider (an adapter seam, not a domain port)
The lock is used **only** by the FAISS index adapter — never by `domain`/`orchestration` (`EnrollmentService` just calls
`upsert`/`delete`; the adapter owns the lock). So the seam stays **inside `adapters/`**, keeping the layering invariant
intact (no new domain port). A `WriteLockProvider` Protocol (`adapters/vector_index/_locks.py`): `acquire(school_id) ->
AbstractAsyncContextManager`, held across the whole read-modify-write; different schools never contend.
- **`InProcLockProvider`** (Option A, default): the per-school `asyncio.Lock` registry **moved out of
  `_faiss_cache.IndexCache`** into this provider. The container memoizes **one** provider per process, so the registry
  is process-wide and outlives the FAISS LRU cache (preserving 0011's "the lock registry outlives eviction"). Behaviour
  is byte-for-byte the current Option A.
- **`RedisLockProvider`** (Option B, `adapters/vector_index/_redis_locks.py`):
  `redis.lock(f"faiss:lock:{school_id}", timeout=lease_s, blocking=True, blocking_timeout=wait_s)` — `redis.asyncio`'s
  token-checked `Lock` (`SET NX PX` + a Lua compare-and-del release), reusing the **shared** Redis client the container
  already builds for the queue (closed once in `aclose`).

### 2. Fail-LOUD (the deliberate opposite of BP8c's fail-open rate limiter)
A lock-backend outage (`RedisError`/`OSError`) or an acquire that exceeds `wait_s` (redis `acquire()` returns `False`)
**raises `LockAcquisitionError`** (→ ML 500 → the backend records `enrollment_status=failed`, retryable, never blocks
account creation per 0026) — **never** a silent unlocked write, because an unlocked FAISS write under concurrency risks
a **lost enrollment**. Correctness > availability here (unlike a missed throttle). `_RedisLockCtx` wraps the redis lock
so the error mapping + a best-effort release live in the adapter, keeping the FAISS index domain-clean.

### 3. The FAISS adapter uses the provider; the critical section is unchanged
`FaissPerSchoolVectorIndex.__init__` gains `lock_provider: WriteLockProvider | None = None` (defaults to
`InProcLockProvider()` for standalone construction/tests; the container always injects the shared one). The two
`async with self._locks.acquire(school_id):` sites wrap exactly the existing `load → _apply_* in a thread → store.save`
(`meta.json` written **last** as the commit point) `→ cache.invalidate` — for both `upsert` and `delete`.

### 4. Wiring + config
`faiss_lock_impl: str = "inproc"` (inproc | redis) + `faiss_lock_lease_s: float = 60.0` + `faiss_lock_wait_s: float =
30.0`; a `FAISS_LOCK_REGISTRY`; a memoized `container.write_lock_provider()` injected into `vector_index()`. New
`ML_FAISS_LOCK_IMPL`/`_LEASE_S`/`_WAIT_S` in `.env.example`; a `docker-compose.yml` comment on scaling enrollment (set
`ML_FAISS_LOCK_IMPL=redis` + raise the `ml-service` replica count). No default change.

## Honest limits (documented)

- **Lease-loss on a slow write (the classic TTL-lock hazard):** if an index rebuild+upload outruns `lease_s` (60s), the
  Redis lock **auto-expires while a holder is still writing** — another replica could acquire and interleave a write. We
  can't detect it before the fact; the best-effort release logs a **loud `faiss_write_lock_lease_lost`** (with a "raise
  `ML_FAISS_LOCK_LEASE_S`" hint) when it fires. So **`lease_s` must exceed the slowest index write** — a documented,
  monitorable operational invariant (v1 school sizes are well under 60s). Lease auto-extension is a future refinement.
- **`wait_s` (30s) vs the backend's `BE_ML_HTTP_TIMEOUT_S` (60s):** a contender may block up to `wait_s` before the
  enroll runs; `wait_s` + the enroll must stay under the backend's read timeout, else the BE `ReadTimeout`s while the ML
  still holds the lock (wasted work). Defaults leave headroom for a fast enroll; tune per deployment.
- **`redis.asyncio.Lock` stores its token in thread-local storage**, so acquire + release must run on the same thread —
  they do (both awaited on the event-loop thread; only the pure rebuild is offloaded). Documented so a future refactor
  doesn't silently break it.
- **In-process (Option A) is per-replica** — it's the fleet lock *only* single-replica; multi-replica **requires**
  Option B.

## Verification

- ML gate green: ruff + mypy + **full suite 137 passed / 10 skipped** + layering (the Protocol + redis adapter live in
  `adapters/`; `domain`/`orchestration` untouched save a pure new error class). Coverage: in-proc mutual-exclusion +
  cross-school concurrency + same-lock-per-school; an **always-on** fail-loud test (dead port → `LockAcquisitionError`)
  + the `__aexit__` release-swallow (both `LockNotOwnedError` + generic `RedisError`); the FAISS adapter **uses the
  injected provider** (a spy asserts both `upsert`+`delete` acquire the school's lock); the container
  `write_lock_provider()` inproc/redis selectors + `ConfigurationError` on an unknown impl + memoization.
- **Gated real-Redis** (skipif `ML_TEST_REDIS_URL` unset — unique keys, short leases, always released; never the dev
  Redis destructively): same-school **mutual exclusion**, **different-school concurrency**, and **fail-loud on a
  `wait_s` timeout**. All 3 pass on a real Redis.
- **2× review→fix loop** (two agents). **R1 (correctness/concurrency): no blocker, ship-ready** — verified the cardinal
  invariant (no `store.save` without the lock), fail-loud on both the connection-error and wait-timeout paths, the
  singleton wiring, no re-entrancy, and the shared-redis lifecycle; flagged the lease-loss logging + the thread-local
  invariant. **R2 (edge/tests/config): no code blocker** — flagged the container/adapter/​release test gaps.
  **Applied:** loud `LockNotOwnedError` logging + the thread-local comment; the container-selector, adapter-uses-provider
  spy, and release-swallow tests; and pinned `faiss_lock_impl` in the container-test settings (pydantic-settings was
  reading `.env` for the unset field → non-deterministic).
- **Live multi-replica smoke** (two API replicas racing an enroll for one school against a real Redis) is noted pending
  a running multi-replica stack, per prior phases.

## Follow-ups

**BP8e** retention/erasure (the last BP8 slice, per `product/03`). Optional BP8d polish: Redis **lease auto-extension**
for very slow writes; a **503** (vs 500) for `LockAcquisitionError` so monitors distinguish "lock backend down, retry";
enabling `ML_FAISS_LOCK_IMPL=redis` + a >1 `ml-service` replica count in the prod compose/manifests.
