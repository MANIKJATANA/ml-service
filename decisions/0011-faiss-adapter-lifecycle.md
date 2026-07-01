# 0011 — FAISS per-school adapter: Option A, pluggable index store, rebuild-on-write

**Date:** 2026-07-02
**Status:** Accepted

## Context

Phase 2 implements the `VectorIndex` port with FAISS (architecture §6, §7). §7
leaves a few choices to the implementation: how writes are serialized, where index
files live, and how a student's multiple vectors are removed/collapsed.

## Decision

- **`IndexFlatIP` per school**, one file-backed index per `school_id` (cosine ==
  inner product on our L2-normalized vectors). Tenant isolation is structural:
  every call names a `school_id` and only that school's files are touched (NFR-3).
- **Write serialization = Option A (in-process lock).** A per-school
  `asyncio.Lock` (in `_faiss_cache.IndexCache`) serializes `upsert`/`delete`.
  Combined with a single-replica enrollment deployment this is the fleet-wide
  lock (§7.4). The lock registry outlives LRU eviction. Migration to Option B
  (Redis lock) is the same code path when enrollment must scale out.
- **Pluggable index store** (`_index_store.py`): `LocalFsIndexStore` (dev /
  shared Docker volume) and `SupabaseIndexStore` (prod). Three objects per school
  — `index.faiss`, `id_map.json`, `meta.json` — with **`meta.json` written last**
  as the commit point (§7.1/§7.4). `meta.version` is bumped on every write and is
  the cache-invalidation key.
- **Rebuild-on-write.** Each write reconstructs the surviving vectors
  (`reconstruct_n`), drops the target student's rows (replace-not-append, FR-E3),
  appends the new ones, and rebuilds a fresh `IndexFlatIP`. This sidesteps FAISS
  row-id shifting on removal; brute-force but fine at v1 scale (§7.4).
- **Read path** re-checks `meta.version` (cheap `read_meta`) against a per-worker
  LRU cache and reloads on staleness. It **fails loud** with
  `EmbeddingVersionMismatch` when the stored `embedding_model_version` differs
  from the configured embedder — never search a stale-model index (§7.3).
- **Over-fetch + collapse in the adapter.** Because multi-vector enrollment lets
  one student own several rows, `search` fetches `top_k × overfetch` hits then
  collapses to each student's best before returning `top_k` — honouring the port
  contract that `search` yields at most one candidate per student
  (see `domain/ports.py`; the decision function re-collapses defensively).

## Why

- Matches architecture §7 exactly where it is prescriptive; picks the simplest
  correct option where it is not.
- Rebuild-on-write keeps `id_map` a trivial `row → student_id` list and avoids
  subtle FAISS deletion bugs, at a cost that is negligible for ≤50k vectors.

## Alternatives rejected

- **`IndexIDMap2` + `remove_ids`** — more moving parts; deletion/rowid semantics
  are easy to get wrong. Revisit with `IndexHNSWFlat`/Milvus at scale (req §11).
- **Option B (distributed lock) now** — unneeded at v1's single-replica
  enrollment; documented as the scale-up.
