# 0008 — Domain core design (Phase 1)

**Date:** 2026-07-01
**Status:** Accepted

## Context

Phase 1 of building the ML service (see the approved plan) implements the pure
`domain/` layer and the `orchestration/` services from the specs, with no heavy
deps and no GPU — fully unit-testable. A few concrete choices were needed where
the specs leave room or where requirements §9's illustrative signatures don't
fit the async, at-least-once architecture of §6/§7.

## Decisions

- **Pure, dependency-light domain.** `domain/` uses stdlib only — frozen
  `@dataclass(frozen=True, slots=True)` value objects and `enum.StrEnum`, not
  pydantic. pydantic *is* a third-party lib; keeping it out of `domain/` protects
  the layering boundary (NFR-1). pydantic stays at the edges (API models, settings).
  Immutability makes the resolved `Thresholds` safe to pass by value into the pure
  decision function.
- **Async ports, one sync exception.** All ports are `async` except
  `VideoFrameExtractor`, which stays a lazy sync `Iterator[Frame]` (req §9). The
  architecture already chose async I/O (SQLAlchemy async + asyncpg, redis async,
  an `asyncio.Lock` in the FAISS cache, §6/§7); a uniformly async service lets the
  async API route and the async worker call the same code. Sync ML libs
  (InsightFace, faiss) are wrapped with `anyio.to_thread.run_sync` inside their
  Phase-2 adapters; worker concurrency stays 1/pod. Note that the sync
  `VideoFrameExtractor` iterator runs *on the event loop* as the inference path
  drains it — it is the one blocking call left in the async pipeline, so Phase 2/3
  must pump it off-thread (e.g. `anyio.to_thread`/a producer queue) to avoid
  stalling the loop while decoding video.
- **Port signature divergences from req §9** (illustrative, not binding):
  - `VectorIndex.upsert` takes a **batch** (`list[Embedding]`) so one call atomically
    *replaces* a student's vectors (FR-E3). Singular-called-N-times would append.
  - `JobQueue` exposes `consume() -> AsyncIterator[JobLease]` plus `ack`/`nack` with
    an opaque receipt, for at-least-once delivery + dead-letter (architecture §8.4).
- **Inference returns metrics, doesn't emit them.** `InferenceService.process`
  returns a `JobOutcome` (the req §13 counters + model versions); the Phase-4
  worker turns it into Prometheus metrics. This keeps `orchestration/` import-pure
  (no `prometheus_client`).
- **Testing honours "no fakes" for the shipped service.** Only real adapters are
  wired into runnable paths (Phase 2+). The decision matrix is tested as a pure
  function. The orchestration services are unit-tested with deterministic,
  **test-only** doubles in `tests/fakes.py` that feed controlled scores/frames —
  things real face images can't reproduce reliably. These doubles are never
  importable by the service: `tests/test_layering.py` (the AST form of the §5 grep)
  forbids `domain/`/`orchestration/` from importing concrete libs. Real-adapter
  integration + e2e tests come in Phase 2.

## Config touched

- `tests/conftest.py` inserts the tests dir on `sys.path` so the shared
  `fakes.py` is importable under pytest's `--import-mode=importlib`.
- Root `pyproject.toml` gains a mypy override (`module = ["fakes"]`,
  `ignore_missing_imports = true`) so the bare import doesn't trip strict mypy;
  `fakes.py` itself is still type-checked under its own path.

## Verification

`uv run ruff check .`, `uv run mypy .` (31 files, clean), and
`uv run pytest services/ml_service` (52 passed) all green; the layering grep
returns nothing. (Counts updated post-Round-3; the original Phase-1 figures were
30 files / 33 passed.)

## Alternatives rejected

- **pydantic in domain** — simplest validation, but breaks the pure-layer rule.
- **All-sync ports** (literal req §9) — would force the async API/worker to bridge
  per call; async-with-executor-in-adapter is cleaner and matches §6/§7.
- **Shipping in-memory fake adapters** (vector index / repo) — contradicts the
  "no fakes" directive; the real faiss + Postgres adapters are built in Phase 2
  and tested for real.

## Known consideration

When the same student is detected across multiple frames, dedupe keeps the
highest-confidence detection and carries *its* `needs_review` flag — so a 0.95
ambiguous detection beats a 0.93 confident one (the kept record is `needs_review`).
The spec doesn't define cross-frame `needs_review` resolution; we deliberately take
it from the kept highest-confidence detection rather than, say, OR-ing the flags.

## Round-2 amendment (2026-07-01) — per-student candidate uniqueness

The decision logic assumes the two candidates it compares are *distinct students*.
That only holds if `VectorIndex.search` returns **≤1 candidate per `student_id`** —
which the Phase-2 faiss adapter must guarantee by over-fetching (k' > top_k) and
collapsing each student to their best hit before returning. As a second line of
defence, `apply_threshold_and_gap` now itself collapses per student and sorts by
score descending, so a search that accidentally returns a student twice can no
longer manufacture a false ambiguous match. Relatedly, architecture §7.4's "remove
old row" must under multi-vector enrollment remove **all** rows for a student (not a
single row) for replace-not-append (FR-E3) to hold.
