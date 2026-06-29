# Photo Distribution ML Service — Architecture Design

**Version:** 1.0
**Pairs with:** `ml-service-requirements.md` v1.0
**Status:** v1 architecture, ready for implementation

---

## 1. Architectural Style

Hexagonal architecture (ports and adapters). The choice is forced by the requirements doc itself — NFR-1 and NFR-2 demand independent swappability of ML stack and storage, and Section 9 already defines the ports as Python `Protocol`s. The orchestrators (`EnrollmentService`, `InferenceService`) live in a pure domain layer that imports nothing concrete. Everything ML-specific (FAISS, InsightFace) and everything I/O-specific (Azure Blob, Postgres, Redis) lives behind an adapter that satisfies one of the eight ports.

Two execution modes:

- **Synchronous HTTP** for enrollment. Latency budget is small (a few hundred ms per photo), throughput is bounded by school onboarding, no queue needed.
- **Asynchronous queue-driven workers** for inference. One job per media item, horizontally scalable workers, jobs can take seconds (image) to minutes (long video).

Both modes share the same `EnrollmentService` / `InferenceService` code paths — the API and the worker are thin shells that build a job context and call the service.

---

## 2. Sequence — Enrollment

```
Core system          Enrollment API       EnrollmentService     FaceDetector  FaceEmbedder  VectorIndex
     │                      │                      │                  │             │             │
     │  POST /enroll        │                      │                  │             │             │
     │  {school_id,         │                      │                  │             │             │
     │   student_id,        │                      │                  │             │             │
     │   photos[]}          │                      │                  │             │             │
     │ ────────────────────►│                      │                  │             │             │
     │                      │  enroll(req)         │                  │             │             │
     │                      │ ────────────────────►│                  │             │             │
     │                      │                      │  for each photo: │             │             │
     │                      │                      │ ────────────────►│ detect()    │             │
     │                      │                      │◄──── [FaceBox]   │             │             │
     │                      │                      │                                              │
     │                      │                      │  pick largest box (log warn if >1)           │
     │                      │                      │ ────────────────────────────►│ embed()       │
     │                      │                      │◄──── Embedding               │               │
     │                      │                      │                                              │
     │                      │                      │  (after all photos)                          │
     │                      │                      │ ─────────────────────────────────────────►│ upsert(school_id,
     │                      │                      │                                            │   student_id,
     │                      │                      │                                            │   embeddings,
     │                      │                      │                                            │   meta={model_ver})
     │                      │                      │◄─────────────────────────────────────────│
     │                      │◄── per-photo results │                                              │
     │ ◄────── 200 OK ──────│                      │                                              │
```

Notes:

- Per-photo failure (no face, multiple faces handled, low quality) does **not** abort the request — FR-E4. Each photo gets its own status in the response.
- The upsert is a single call that takes all valid embeddings for the student — the adapter is free to batch internally. This is also the idempotency boundary (FR-E3): the adapter must replace, not append.
- The `meta` carried into upsert includes `embedding_model_version` so the index file can be reconciled later (see FAISS lifecycle, §7).

---

## 3. Sequence — Inference

```
Core    JobQueue   Worker   InferenceService   MediaStore  Thresholds  Detector  Embedder  VectorIndex  MatchRepo
 │         │         │             │                │           │          │         │           │           │
 │ enqueue │         │             │                │           │          │         │           │           │
 ├────────►│         │             │                │           │          │         │           │           │
 │         │ consume │             │                │           │          │         │           │           │
 │         ├────────►│             │                │           │          │         │           │           │
 │         │         │  process()  │                │           │          │         │           │           │
 │         │         ├────────────►│                │           │          │         │           │           │
 │         │         │             │  fetch(uri)    │           │          │         │           │           │
 │         │         │             ├───────────────►│           │          │         │           │           │
 │         │         │             │◄── bytes ──────┤           │          │         │           │           │
 │         │         │             │                │           │          │         │           │           │
 │         │         │             │  get_thresholds(school_id) │          │         │           │           │
 │         │         │             ├───────────────────────────►│          │         │           │           │
 │         │         │             │◄── {match, gap} ───────────┤          │         │           │           │
 │         │         │             │                                                                          │
 │         │         │             │  [if video: frames = extract(bytes, fps); else frames = [image]]         │
 │         │         │             │                                                                          │
 │         │         │             │  for frame in frames:                                                    │
 │         │         │             ├──────────────────────────────────────►│ detect()                         │
 │         │         │             │◄── [FaceBox] ────────────────────────│                                   │
 │         │         │             │    for face in faces:                                                    │
 │         │         │             ├─────────────────────────────────────────────────►│ embed()               │
 │         │         │             │◄── Embedding ─────────────────────────────────────│                      │
 │         │         │             ├──────────────────────────────────────────────────────────────►│ search(school_id, emb, top_k)
 │         │         │             │◄── [Candidate] ───────────────────────────────────────────────│
 │         │         │             │  apply threshold + gap logic (§6.2 of req)                              │
 │         │         │             │  buffer matches keyed by (student_id, media_id)                         │
 │         │         │             │  keep best confidence; record frame_ts and bbox                         │
 │         │         │             │                                                                          │
 │         │         │             │  dedupe → list[MatchRecord]                                              │
 │         │         │             ├──────────────────────────────────────────────────────────────────────────►│ save_batch()
 │         │         │             │◄─────────────────────────────────────────────────────────────────────────│
 │         │         │             │  emit metrics (§13 of req)                                               │
 │         │         │◄────────────│                                                                          │
 │         │         │  ack job    │                                                                          │
 │         │◄────────│             │                                                                          │
```

Critical correctness points baked into this flow:

1. **Threshold resolution happens once per job**, not once per face. The `Thresholds` object is captured in job context and passed to the decision function as a value. This makes the per-face inner loop pure.
2. **The dedupe step is in-memory in the worker**, keyed on `(student_id, media_id)`. The DB unique constraint is the second line of defence (FR-I7), not the first — defer to the worker so a single media item doesn't hit the DB with conflicting rows.
3. **Threshold and gap values used are captured per match record** (NFR-4). The worker doesn't re-read thresholds when persisting; it writes back exactly what was used at decision time.
4. **`save_batch` is the only DB write path.** Even if the worker only emits one match, it goes through `save_batch([record])` — keeps the surface area tiny.

---

## 4. Deployment View

```
                   ┌─────────────────┐
                   │   Core system   │
                   └────────┬────────┘
                            │ HTTPS  +  enqueue
              ┌─────────────┼─────────────┐
              ▼                           ▼
   ┌────────────────────┐        ┌────────────────────┐
   │  ML API service    │        │  Redis (queue)     │
   │  FastAPI, 2+ pods  │        │  Streams + consumer│
   │  CPU-only          │        │  groups            │
   └─────────┬──────────┘        └─────────┬──────────┘
             │                              │ consume
             │                              ▼
             │                   ┌──────────────────────┐
             │                   │  Inference workers   │
             │                   │  GPU pool (T4/A10),  │
             │                   │  N replicas, auto-   │
             │                   │  scale on queue lag  │
             │                   └──────────┬───────────┘
             │                              │
             ▼                              ▼
   ┌──────────────────────────────────────────────────┐
   │            Shared backing services               │
   │                                                  │
   │  Postgres (matches, schools, thresholds)         │
   │  Object storage (media bytes + FAISS index files)│
   │  Prometheus + Grafana (metrics)                  │
   │  Loki / OTel collector (logs + traces)           │
   └──────────────────────────────────────────────────┘
```

Sizing rules of thumb:

- **API pods**: CPU only, very small. Scale on RPS. Enrollment is rare relative to inference.
- **Inference workers**: GPU required for any throughput target above a handful of jobs/min. A single T4 handles ~30–60 face embeddings/sec with ArcFace at 112×112. Worker concurrency inside a pod = 1 (don't multiplex GPU); horizontal scale via more pods.
- **Redis**: single-node is fine for v1. Streams give you consumer groups (durable, at-least-once) and lag metrics for autoscaling. Migrate to Redis Cluster only if you hit memory pressure from large backlogs.
- **Object storage**: Azure Blob (matches your existing stack from Auditify). One container for raw media (already provisioned by core), one container for FAISS index files keyed by `school_id`.
- **Postgres**: single primary + read replica is more than enough at v1 scale. Match rows are append-only.

---

## 5. Folder / Module Structure

This is the concrete mapping from Section 9 of the requirements to code modules. Strict layering: `domain` imports nothing else; `orchestration` imports only `domain`; `adapters/*` may import third-party libs; `api/`, `workers/`, `wiring/` are the only modules that import adapters.

```
ml_service/
├── domain/                        # Pure, no third-party deps
│   ├── __init__.py
│   ├── models.py                  # FaceBox, Embedding, Candidate, Thresholds,
│   │                              # MatchRecord, InferenceJob, Frame
│   ├── ports.py                   # All 8 Protocols from req §9
│   ├── decision.py                # Pure function: apply_threshold_and_gap()
│   └── errors.py                  # EnrollmentError, InferenceError, etc.
│
├── orchestration/                 # Depends only on domain
│   ├── __init__.py
│   ├── enrollment.py              # class EnrollmentService
│   └── inference.py               # class InferenceService
│
├── adapters/                      # Each subpackage = one port's impls
│   ├── detectors/
│   │   ├── scrfd_insightface.py   # default
│   │   └── retinaface_insightface.py
│   ├── embedders/
│   │   ├── arcface_insightface.py # default (buffalo_l)
│   │   └── facenet.py             # optional alt
│   ├── vector_index/
│   │   ├── faiss_per_school.py    # default (v1)
│   │   ├── milvus.py              # future
│   │   └── _faiss_cache.py        # in-memory LRU + lock, internal
│   ├── media_store/
│   │   ├── azure_blob.py          # default (matches your stack)
│   │   ├── s3.py
│   │   └── local_fs.py            # tests + dev
│   ├── video/
│   │   ├── decord_extractor.py    # default
│   │   └── opencv_extractor.py    # fallback
│   ├── repository/
│   │   ├── postgres_matches.py    # SQLAlchemy 2.x async
│   │   └── postgres_thresholds.py
│   └── queue/
│       ├── redis_streams.py       # default
│       └── inproc_queue.py        # tests
│
├── api/
│   ├── main.py                    # FastAPI app factory
│   ├── routes/
│   │   ├── enrollment.py          # POST /v1/students, DELETE /v1/students/{id}
│   │   └── health.py              # /healthz, /readyz
│   └── deps.py                    # FastAPI Depends() → wiring
│
├── workers/
│   ├── inference_worker.py        # entrypoint, consumes from JobQueue
│   └── runner.py                  # loop, retry, dead-letter handling
│
├── wiring/
│   ├── settings.py                # pydantic-settings, loads env/yaml
│   ├── container.py               # builds concrete adapters from settings,
│   │                              # returns EnrollmentService / InferenceService
│   └── registry.py                # adapter_impl name → class lookup table
│
├── observability/
│   ├── metrics.py                 # prometheus_client + label set from req §13
│   ├── logging.py                 # structlog config
│   └── tracing.py                 # OTel spans around port calls
│
└── tests/
    ├── unit/
    │   ├── test_decision.py       # threshold + gap matrix
    │   ├── test_inference_service.py  # with in-memory fakes for every port
    │   └── test_enrollment_service.py
    ├── adapters/
    │   ├── test_faiss_per_school.py
    │   ├── test_scrfd.py
    │   └── ...                    # one per adapter
    └── e2e/
        └── test_full_pipeline.py  # docker-compose, real adapters, golden images
```

**The acceptance test for layering:** `grep -r "import faiss\|import cv2\|import insightface\|import boto3" ml_service/domain ml_service/orchestration` must return zero results. Wire this into CI.

---

## 6. Recommended Initial Adapters

| Port | Implementation | Library | Version | Notes |
|---|---|---|---|---|
| `FaceDetector` | SCRFD-10G | `insightface` | `0.7.3+` | Faster than RetinaFace at equivalent accuracy. Comes in the `buffalo_l` model bundle. |
| `FaceEmbedder` | ArcFace R100 (glintr100) | `insightface` | `0.7.3+` | Also in `buffalo_l`. 512-dim embeddings, L2-normalized → use cosine similarity (inner product on normalized vectors). |
| `VectorIndex` | FAISS `IndexFlatIP` per school | `faiss-cpu` | `1.8.0+` | Exact search. Plenty fast for ≤50k vectors per school. Switch to `IndexHNSWFlat` only if a single school crosses ~100k students. |
| `VideoFrameExtractor` | decord | `decord` | `0.6.0+` | 5-10× faster than OpenCV for sampling. Falls back to PyAV if decord is unavailable on the deploy platform. |
| `MediaStore` | Azure Blob | `azure-storage-blob` | `12.x` | Matches your Auditify stack. Use account-key or managed identity. |
| `MatchRepository` | Postgres via SQLAlchemy | `sqlalchemy` + `asyncpg` | SA `2.0+` | Unique constraint on `(media_id, student_id)` does double duty as idempotency guard. |
| `ThresholdProvider` | Postgres (`schools` table) | same | same | Read-through cache with 60s TTL in adapter — schools rarely change thresholds and we don't want a DB hit per job. |
| `JobQueue` | Redis Streams | `redis-py` | `5.0+` | Consumer groups for at-least-once delivery + `XAUTOCLAIM` for stuck job recovery. |

**On `buffalo_l`:** even though SCRFD and ArcFace ship in the same model bundle, they MUST be in separate adapter modules. The detector adapter imports the detector model only; the embedder adapter imports the recognition model only. Otherwise NFR-1 (independent swappability) is broken on day one.

**Embedding dim and similarity convention:** lock this in `domain/models.py`:

```python
EMBEDDING_DIM = 512                # ArcFace R100 output
SIMILARITY_METRIC = "cosine"       # L2-normalize embeddings on creation
```

Every adapter is responsible for emitting normalized vectors. The FAISS adapter uses `IndexFlatIP` (inner product) which equals cosine on normalized inputs.

---

## 7. FAISS Index Lifecycle

This is the trickiest part of v1 because FAISS is a file-backed library running across multiple worker processes that need a consistent view.

### 7.1 Storage layout

```
azure-blob://faiss-indexes/
  school={school_id}/
    index.faiss              # binary FAISS index
    id_map.json              # row_id → student_id mapping (FAISS only stores ints)
    meta.json                # {embedding_model_version, dim, metric, updated_at, version}
```

`meta.json.version` is a monotonically increasing integer bumped on every successful enrollment write. It's the cache invalidation key.

### 7.2 In-memory cache (per worker process)

Each worker process maintains an LRU cache of loaded `(school_id → LoadedIndex)` entries:

```python
LoadedIndex = {
  "index": faiss.Index,         # in memory
  "id_map": dict[int, str],     # row → student_id
  "meta": dict,                 # last-seen meta.json
  "lock": asyncio.Lock,         # serializes mutations within process
}
```

Cache size = config (default 32 schools per worker). LRU eviction. On eviction, just drop the entry — the source of truth is in object storage.

### 7.3 Read path (inference)

```
1. Worker receives job for school_id S.
2. Look up S in process-local cache.
3a. Hit: re-fetch meta.json (HEAD or small GET). If version unchanged → use cached.
3b. Miss or stale version → download index.faiss + id_map.json + meta.json,
    load into memory, insert into cache (evicting LRU if full).
4. Validate meta.embedding_model_version == configured embedder.version. If not,
    raise EmbeddingVersionMismatch and let the worker fail loud — never search
    against a stale-model index.
5. Run search.
```

The meta-check every read is cheap (sub-10ms HEAD request) and avoids the painful case of stale indexes after enrollment.

### 7.4 Write path (enrollment)

Writes must be serialized per school across the entire fleet. FAISS index files are not safe for concurrent rebuild + upload. Options ordered by complexity:

**Option A — single dedicated enrollment worker (recommended for v1).** Run enrollment as its own service deployment with replica count = 1. No distributed locking needed; the process is the lock. All inference workers stay read-only against FAISS.

**Option B — distributed lock per school.** If enrollment must scale horizontally, use Redis with `SET school:{id}:lock <token> NX EX 60`. Acquire → download index → mutate → upload → bump `meta.version` → release. Inference workers detect the bumped version on next read and reload.

Pick A for v1. The migration to B is trivial (it's the same adapter code path) when concurrency demands it.

The actual write sequence inside `FaissPerSchoolVectorIndex.upsert`:

```
1. Acquire lock (Option A: in-process; Option B: Redis).
2. Download current index.faiss + id_map.json + meta.json (or create empty if first enrollment).
3. For each (student_id, embedding):
     - If student_id already in id_map (reverse lookup), remove its old row via
       index.remove_ids(np.array([old_row_id])). FAISS IndexFlatIP supports this.
     - Append new embedding via index.add(); record the new row_id.
4. Save index.faiss locally, upload to blob with overwrite.
5. Update id_map.json, bump meta.version, write meta.json LAST (atomic-ish:
    inference workers key off meta.version, so writing it last is the
    commit point).
6. Invalidate this worker's own cache entry for school_id.
7. Release lock.
```

`IndexFlatIP` is brute-force and rebuilding on every enrollment write is wasteful but fine at v1 scale. When you migrate to `IndexHNSWFlat` or Milvus, this code goes away.

### 7.5 Delete path

`delete(school_id, student_id)`: same lock-download-mutate-upload-bump-version path, using `index.remove_ids()`. Don't compact — FAISS handles deleted slots internally.

### 7.6 Bulk rebuild (model version change)

When `embedder_impl` config changes or `embedder.version` bumps, every index is invalid. A separate offline script:

```
for school in schools:
  for student in students_of(school):
    embeddings = re_embed(reference_photos_of(student))
    new_index.upsert(school.id, student.id, embeddings)
  swap_index_files(school.id)  # atomic blob rename + meta bump
```

Run this on a separate worker pool against a `faiss-indexes-v2/` prefix, then flip configuration. Inference workers pick up the new prefix on next deploy.

---

## 8. Cross-Cutting Concerns

### 8.1 Configuration

Single `Settings` class via `pydantic-settings`, loaded from env vars and YAML. The `wiring/registry.py` is a flat dict mapping adapter names to classes:

```python
DETECTOR_REGISTRY = {
    "scrfd": "ml_service.adapters.detectors.scrfd_insightface:SCRFDDetector",
    "retinaface": "ml_service.adapters.detectors.retinaface_insightface:RetinaFaceDetector",
}
```

`wiring/container.py` reads `settings.detector_impl` (e.g. `"scrfd"`), resolves the dotted path, instantiates with `settings.detector_config`, and injects the result into the service. Same pattern for every port. This is what makes NFR-1 / NFR-2 actually true and not aspirational.

### 8.2 Idempotency, two layers

1. **Worker-side dedupe** during inference (in-memory dict keyed on `(student_id, media_id)`).
2. **DB-side unique constraint** on `(media_id, student_id)` — `save_batch` uses `INSERT ... ON CONFLICT (media_id, student_id) DO UPDATE SET confidence_score = EXCLUDED.confidence_score WHERE EXCLUDED.confidence_score > matches.confidence_score`. Higher-confidence reprocess wins; older lower-confidence rows are upgraded in place.

### 8.3 Observability

Every port call gets an OTel span. Worker emits the metrics from req §13 as Prometheus counters/histograms with labels `school_id`, `embedding_model_version`, `detector_model_version`. Don't put `student_id` on metrics labels — cardinality bomb.

A single `processing_latency_ms` histogram with buckets `[100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000, 120000]` covers image and video both.

### 8.4 Failure modes the worker must handle

| Failure | Behavior |
|---|---|
| MediaStore fetch fails | Retry 3× with backoff; on final failure, NACK job back to queue, after N retries route to dead-letter stream |
| Detector / embedder OOM | Single GPU per pod, restart the pod; job goes back to queue |
| VectorIndex version mismatch | Fail loud, alert; do not silently search |
| Save_batch fails | Retry; if conflicts on unique constraint, treat as success (idempotency) |
| Video corrupt / unreadable | Emit `unknown_faces_total=0` with reason label, mark job complete (don't loop) |

---

## 9. v1 → v2 Migration Hooks

Already baked into the design:

- **FAISS → Milvus**: swap `vector_index_impl` config; backfill script reads existing FAISS files and bulk-inserts to Milvus partitions. Orchestrator code untouched.
- **Open-source models → Azure Face / AWS Rekognition**: write `AzureFaceDetector` and `AzureFaceEmbedder` adapters. The model `version` field becomes the API version string. The fact that detection and embedding might be a single API call in hosted services doesn't matter — call the API in both adapters and cache within the request scope.
- **Redis Streams → SQS / Pub/Sub**: write a new `JobQueue` adapter. The job payload is already vendor-neutral JSON.
- **Manual review workflow (deferred §14.3)**: query `WHERE needs_review = true` against the existing schema. No model change needed.

---

## 10. What Section 16 Asked For, And Where It Is

| Asked | Delivered in |
|---|---|
| Component diagram | Inline visual at top of this response |
| Sequence diagrams (enrollment + inference) | §2 and §3 |
| Deployment view | §4 |
| Folder/module structure mapping to interfaces | §5 |
| Recommended initial adapter choices with versions | §6 |
| FAISS index lifecycle plan | §7 |
