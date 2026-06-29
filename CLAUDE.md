# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working rules (always follow)

- **Record every decision.** Any change or non-trivial decision gets a dated entry in `decisions/` (see `decisions/README.md` for the format). Update the index there.
- **Keep this file current.** When architecture, commands, or conventions change, update CLAUDE.md in the same change.
- **Never push without being asked.** Commit locally if useful, but do not `git push` (or open PRs) until explicitly told to.
- **Self-review.** After making changes, review your own work and fix the issues you introduced before reporting done.
- **Never read `.env` files** (or any secrets files), and never store secrets in memory or in code.

## Status: design phase, no code yet

The repo is git-initialized (`main` branch) with a secrets-safe `.gitignore`, but contains no implementation, build tooling, or tests yet — only the two specification documents:

- `ml-service-requirements.md` — locked v1 requirements (the "what"). Source of truth for functional/non-functional requirements, locked decisions (§8), interface contracts (§9), and data contracts (§10).
- `ml-service-architecture.md` — v1 architecture (the "how"). Source of truth for module layout (§5), adapter choices + versions (§6), and the FAISS index lifecycle (§7).

When implementing, treat both docs as binding. The architecture doc's §5 module tree is the intended layout; §6's adapter table fixes the initial library choices and versions. If a code change contradicts either doc, surface the conflict rather than silently diverging.

## What this service is

A multi-tenant face-recognition service for distributing event photos/videos to the students who appear in them. Two pipelines that share one embedding model version but are otherwise independent:

- **Enrollment** (synchronous HTTP): detect face in reference photos → embed → upsert into a per-school vector index.
- **Inference** (async, queue-driven workers): fetch media → (video) extract frames at fixed FPS → detect → embed → search the school's index → apply threshold/gap decision → dedupe → persist match records.

## Architecture: hexagonal (ports and adapters)

The design exists to satisfy NFR-1/NFR-2 (swap ML stack or storage by config alone). The whole structure depends on strict layering:

- `domain/` — pure, imports no third-party libs. Models, the 8 `Protocol` ports (req §9), and the pure `apply_threshold_and_gap()` decision function.
- `orchestration/` — `EnrollmentService` / `InferenceService`. Imports only `domain`.
- `adapters/` — one subpackage per port; the only place concrete libs (faiss, insightface, azure, redis, sqlalchemy) are imported.
- `api/`, `workers/`, `wiring/` — the only modules allowed to import adapters. `wiring/container.py` builds concrete adapters from config via a name→class registry and injects them into the services.

**Layering invariant (wire into CI):** no concrete ML/IO library may be imported in `domain/` or `orchestration/`. The doc's acceptance test:
```
grep -r "import faiss\|import cv2\|import insightface\|import boto3" ml_service/domain ml_service/orchestration
```
must return nothing. The API and worker are thin shells — both build a job context and call the same service code paths.

## Correctness invariants (do not break these)

These come straight from the specs and are the easy things to get subtly wrong:

- **Tenant isolation (NFR-3, FR-I4):** all matching is strictly within one `school_id`. Enforced at the `VectorIndex` interface. There is no cross-school search in v1.
- **Threshold resolution is once per job, not per face.** Resolve `Thresholds` into the job context, pass it as a value into the pure decision function. Per-school value with global-default fallback when null (req §6.1).
- **Reproducibility (NFR-4):** each match record persists `embedding_model_version`, `detector_model_version`, `threshold_used`, `gap_threshold_used` — the values actually used at decision time, not re-read at write time.
- **Two-layer idempotency (NFR-5):** in-memory worker dedupe keyed on `(student_id, media_id)` first; DB unique constraint on `(media_id, student_id)` as the second line of defence. `save_batch` is the only DB write path and uses `INSERT ... ON CONFLICT` where higher confidence wins.
- **Decision logic (req §6.2):** top-K=2. ≥threshold filter; 0 → unknown (log only, no record, FR-I8); 1 → emit; 2 → emit top-1 alone if `(top1-top2) > gap`, else emit both with `needs_review=true`.
- **Embedding convention:** 512-dim ArcFace, L2-normalized; cosine similarity via FAISS `IndexFlatIP`. Lock `EMBEDDING_DIM=512` / `SIMILARITY_METRIC="cosine"` in `domain/models.py`; every adapter must emit normalized vectors.
- **Detector and embedder stay in separate adapter modules** even though both ship in the `buffalo_l` bundle — sharing the import breaks NFR-1.
- **Enrollment is replace-not-append (FR-E3);** per-photo failures don't abort the request (FR-E4).

## FAISS lifecycle (the trickiest part — see architecture §7)

File-backed index per school in blob storage (`index.faiss` + `id_map.json` + `meta.json`). `meta.json.version` is the cache-invalidation key, bumped on every successful write and written **last** as the commit point. Each worker keeps an LRU cache of loaded indexes; the read path re-checks `meta.version` (cheap HEAD) and reloads on staleness. On read, validate `meta.embedding_model_version` matches the configured embedder and **fail loud** on mismatch — never search a stale-model index. v1 serializes writes via a single-replica enrollment deployment (Option A); per-school Redis lock (Option B) is the documented scale-up.

## Planned stack (architecture §6)

Python, hexagonal. FastAPI (CPU API pods) + GPU inference workers consuming Redis Streams. InsightFace (SCRFD detector + ArcFace embedder), faiss-cpu, decord for video frames, Azure Blob media store, Postgres via SQLAlchemy 2.x async (asyncpg), pydantic-settings for config. Observability: prometheus_client + structlog + OTel spans around port calls (never label metrics with `student_id` — cardinality bomb).

No build/test commands exist yet. When scaffolding, add them here.
