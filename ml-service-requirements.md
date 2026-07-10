# Photo Distribution ML Service — Requirements Document

**Version:** 1.0
**Status:** Locked for architecture phase
**Scope:** ML service only (integration with core system is downstream)

---

## 1. Background & Problem Statement

The platform supports **N schools**, each with **X students**. When a school hosts an event, photos and videos from that event are uploaded. The platform must distribute the right media to the right students by identifying which students appear in each media item.

This document specifies the **ML service** responsible for:

1. Maintaining a per-student face representation (embedding) for every enrolled student.
2. Processing event media (images + videos) to detect faces and match them against enrolled students of that school.
3. Emitting structured match records that the core system uses to fan out media to students.

The ML service does **not** handle upload, storage management, notifications, consent, or distribution UX — those belong to the core system.

---

## 2. Goals & Non-Goals

### Goals
- Accurate face matching scoped strictly within a single school's student set.
- Pluggable ML stack — face detector, face embedder, and vector index must each be independently replaceable with no change to business logic.
- Pluggable storage layer — media source and metadata sink abstracted.
- Idempotent processing — re-running the same media produces no duplicate records.
- Reproducibility — every match record carries the model versions and thresholds used.
- Async / batch friendly — events can produce hundreds of media items.

### Non-Goals (for v1)
- Cross-school search or matching.
- Manual review UI (data model supports it via `needs_review`, but the workflow is out of scope).
- Privacy / consent / legal compliance flows (DPDP, COPPA, etc.) — flagged for later.
- Re-enrollment cadence policy for growing children — flagged for later.
- Handling of "unknown faces" (people who appear in photos but are not enrolled students) — flagged for later.

---

## 3. Core Concepts & Terminology

| Term | Definition |
|---|---|
| **School** | Tenant boundary. All matching happens strictly within a school. |
| **Student** | A person enrolled within a school, with one or more reference face photos. |
| **Embedding** | A numeric vector representation of a face produced by the face embedder model. |
| **Enrollment** | One-time (or update-triggered) process of generating and storing embeddings for a student. |
| **Inference** | Per-event-media process of detecting faces and matching them to enrolled students. |
| **Match record** | The output row written to the matches table for each (student, media) match found. |
| **Vector index** | Storage + similarity search structure holding student embeddings, scoped per school. |
| **Confidence score** | Similarity score between a detected face's embedding and a student's stored embedding. |
| **Threshold** | Minimum confidence score for a match to be emitted. Resolved per-school (with global fallback). |
| **Gap threshold** | Minimum difference between top-1 and top-2 candidate scores for top-1 to be treated as a confident single match. |

---

## 4. Two ML Workflows

The service has **two distinct pipelines**. They MUST share the same embedding model version, but are otherwise independent.

### 4.1 Enrollment Pipeline

**Trigger:** Core system calls the enrollment API when a student is added or their reference photos are updated.

**Input:**
- `school_id`
- `student_id`
- One or more reference face photos

**Steps:**
1. For each reference photo, detect face(s).
2. If a single clear face is detected, generate an embedding.
3. If multiple faces are detected in a reference photo, reject or pick the largest (decision: pick the largest face for v1, log a warning).
4. Upsert embedding(s) into the school's vector index, keyed by `student_id`.

**Output:** Success/failure response with per-photo status.

### 4.2 Inference Pipeline

> **Amended by [decisions/0027](decisions/0027-events-media-enqueue-status.md) (Phase 5):**
> the queue now carries **one job per event**, not per media item. The core system
> enqueues `{school_id, event_id}` when its operator presses "Process" for an event; the
> worker marks the event row `processing`, reads the core system's `events`/`media`
> tables from the **shared DB** to enumerate the photos, **skips any photo already
> `completed`** (the backend `media.processing_status` column — idempotent redistribute),
> runs the per-photo steps below on the rest, **writes each finished photo's status
> `completed`** on its backend row, then marks the event `completed`. So the ML worker
> **owns the job-status writes** and the core system needs no poller. Per-photo detection
> writes are unchanged. The per-media trigger + payload below are superseded; steps 1–9
> now describe the **per-photo** work the worker does for each rostered photo.

**Trigger:** Core system enqueues one job per **event** (`{school_id, event_id}`); the
worker expands it into the event's photos via the shared-DB `media` roster.

**Per-photo input** (derived from the roster, not the queue message):
- `media_id`
- `media_uri`
- `school_id`
- `event_id`
- `media_type` ∈ {`image`, `video`}

**Steps (per rostered, not-yet-processed photo):**
1. Fetch media bytes from the abstracted media store.
2. If video: extract frames at fixed FPS (config).
3. For each image/frame, detect all faces.
4. For each detected face, generate an embedding.
5. Search the school's vector index (top-K, where K = config, default 2).
6. Apply per-school threshold and gap logic (see Section 6).
7. Deduplicate per (student, media) — keep the best confidence and a representative frame.
8. Write match records via the abstracted match repository.
9. Emit per-job metrics.

**Output:** Match records + `media_detections` persisted per photo; aggregate metrics
emitted; the event job marked complete. A per-photo fetch/decode error is skipped (a
later redistribute retries it); a stale-index version mismatch aborts the event.

---

## 5. Functional Requirements

### 5.1 Enrollment API
- **FR-E1:** Service exposes an API to add/update student embeddings given `school_id`, `student_id`, and reference photo(s).
- **FR-E2:** Service exposes an API to delete a student's embeddings.
- **FR-E3:** Enrollment is idempotent — re-enrolling the same student replaces prior embeddings.
- **FR-E4:** Enrollment failures (no face detected, low quality) are returned per-photo and do not block other photos.

### 5.2 Inference Job
- **FR-I1:** Service accepts inference jobs via a queue interface.
- **FR-I2:** For video, the service extracts frames at a configurable fixed FPS (default 1 fps).
- **FR-I3:** For each face detected, the service generates an embedding and searches the school's vector index.
- **FR-I4:** Search is **strictly scoped to the provided `school_id`** — no cross-school leakage.
- **FR-I5:** Service applies per-school threshold and gap logic to decide what to emit (see Section 6).
- **FR-I6:** Service deduplicates per `(student_id, media_id)` — one row per pair, keeping the highest-confidence detection.
- **FR-I7:** Service is idempotent on `(media_id, student_id)` — reprocessing the same media does not create duplicate rows.
- **FR-I8:** Unknown faces (no candidate above threshold) are logged but no record is emitted.

### 5.3 Match Output
- **FR-M1:** Each match emitted is written to a `matches` table (or equivalent sink) via the abstracted repository.
- **FR-M2:** Each match record includes model versions, detector version, threshold used, and a `needs_review` flag.

---

## 6. Threshold & Gap Logic

### 6.1 Threshold Resolution (Per-School with Global Fallback)

Schools may override thresholds. The service resolves thresholds via a `ThresholdProvider` interface:

1. Look up `match_confidence_threshold` and `gap_threshold` on the school row.
2. If either is `NULL`, fall back to the global default from config.

### 6.2 Match Decision Logic

For each detected face, the vector index returns top-K candidates (K = `top_k`, default 2). Apply the following:

```
candidates = vector_index.search(school_id, embedding, top_k=K)
filtered   = [c for c in candidates if c.score >= match_confidence_threshold]

if len(filtered) == 0:
    # unknown face, no record emitted
    continue

if len(filtered) == 1:
    emit(filtered[0], needs_review=False)
    continue

top1, top2 = filtered[0], filtered[1]

if (top1.score - top2.score) > gap_threshold:
    # confident single match
    emit(top1, needs_review=False)
else:
    # ambiguous — emit both for downstream review
    emit(top1, needs_review=True)
    emit(top2, needs_review=True)
```

---

## 7. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-1 | **Model swappability.** Face detection, face embedding, and vector index must each be replaceable by changing configuration/wiring only. Business logic must depend only on interfaces. |
| NFR-2 | **Storage swappability.** Media source (S3 / Azure Blob / GCS / local FS) and metadata sink (Postgres / MySQL / Mongo) must be replaceable behind interfaces. |
| NFR-3 | **Tenant isolation.** A school's embeddings are never matched against another school's media. Enforced at the `VectorIndex` interface level. |
| NFR-4 | **Reproducibility.** Every match record carries `embedding_model_version`, `detector_model_version`, `threshold_used`, `gap_threshold_used`. |
| NFR-5 | **Idempotency.** `(media_id, student_id)` is the unique key on match records. |
| NFR-6 | **Async-friendly.** Inference runs via a job queue; service can scale workers horizontally. |
| NFR-7 | **Observability.** Per-job metrics: faces detected, candidates above threshold, matches emitted, ambiguous matches, unknowns, end-to-end latency, frames processed (video). |
| NFR-8 | **Config-driven.** All tunables (thresholds, FPS, top_k, model paths) are configuration, not code. |

---

## 8. Locked Decisions

| # | Topic | Decision |
|---|---|---|
| 1 | Threshold strategy | **Per-school**, DB-driven (`schools.match_confidence_threshold`, `schools.gap_threshold`); global default fallback when null |
| 2 | Multi-match handling | Top-K = 2. If `score[0] − score[1] > gap_threshold` → emit only top-1 (`needs_review=false`). Else emit both with `needs_review=true` |
| 3 | Video sampling | Fixed FPS (config, default `1.0`) |
| 4 | ML models | **Open-source** stack (e.g., RetinaFace / SCRFD for detection, ArcFace / InsightFace for embedding). All accessed via interfaces — implementation can be swapped to hosted (AWS Rekognition, Azure Face) later |
| 5 | Vector index | **FAISS, per-school index** (one index per school). Behind `VectorIndex` interface. Migration target documented in Section 11 |
| 6 | Enrollment | Dedicated API for add/update/delete of student embeddings |
| 7 | Multi-face reference photos | Pick the largest face, log a warning |
| 8 | Unknown faces | Log only, no record |

### Deferred (will revisit)
- Re-enrollment cadence (children's faces change over time)
- Privacy / DPDP / COPPA compliance
- Manual review UI workflow
- Storage / retention policy for embeddings

---

## 9. Core Abstractions (Interface Contracts)

Business logic (the orchestrator) depends **only** on these interfaces. Concrete implementations live in adapter modules and are wired via config/DI.

```python
# Face detection
class FaceDetector(Protocol):
    version: str
    def detect(self, image_bytes: bytes) -> list[FaceBox]: ...

# Face embedding
class FaceEmbedder(Protocol):
    version: str
    def embed(self, image_bytes: bytes, face_box: FaceBox) -> Embedding: ...

# Vector index — per-school scoping enforced at interface level
class VectorIndex(Protocol):
    def upsert(self, school_id: str, student_id: str,
               embedding: Embedding, metadata: dict) -> None: ...
    def search(self, school_id: str, embedding: Embedding,
               top_k: int) -> list[Candidate]: ...
    def delete(self, school_id: str, student_id: str) -> None: ...

# Media source
class MediaStore(Protocol):
    def fetch(self, media_uri: str) -> bytes: ...

# Video frame extraction
class VideoFrameExtractor(Protocol):
    def extract(self, video_bytes: bytes,
                fps: float) -> Iterator[Frame]: ...

# Match record sink
class MatchRepository(Protocol):
    def save_batch(self, records: list[MatchRecord]) -> None: ...
    def exists(self, media_id: str, student_id: str) -> bool: ...

# Threshold resolution
class ThresholdProvider(Protocol):
    def get_thresholds(self, school_id: str) -> Thresholds: ...
    # Thresholds = {match_confidence, gap}

# Job queue
class JobQueue(Protocol):
    def enqueue(self, job: InferenceJob) -> None: ...
    def consume(self) -> InferenceJob: ...
```

**Rule:** No concrete library (FAISS, InsightFace, boto3, etc.) is imported anywhere outside its adapter module.

---

## 10. Data Contracts

### 10.1 `matches` table

| Column | Type | Notes |
|---|---|---|
| `match_id` | UUID | PK |
| `school_id` | string | tenant key |
| `event_id` | string | |
| `student_id` | string | |
| `media_id` | string | |
| `media_type` | enum | `image` / `video` |
| `confidence_score` | float | |
| `bbox` | json, nullable | face bounding box on representative frame |
| `frame_timestamp_ms` | int, nullable | only for video |
| `needs_review` | boolean | `true` when gap was below threshold |
| `embedding_model_version` | string | |
| `detector_model_version` | string | |
| `threshold_used` | float | |
| `gap_threshold_used` | float | |
| `created_at` | timestamp | |

**Constraints:**
- Unique: `(media_id, student_id)` — enforces idempotency.
- Index: `(school_id, event_id)` for fan-out queries by core system.
- Index: `(school_id, student_id)` for per-student retrieval.

### 10.2 `schools` table (additions only)

| Column | Type | Notes |
|---|---|---|
| `match_confidence_threshold` | float, nullable | per-school override |
| `gap_threshold` | float, nullable | per-school override |

### 10.3 Inference job payload

> **Amended by [decisions/0027](decisions/0027-events-media-enqueue-status.md):** the
> queued payload is now **event-level** — the worker reads the per-photo fields
> (`media_id`, `media_uri`, `media_type`) from the shared-DB `media` roster.

```json
{
  "school_id": "string",
  "event_id": "string"
}
```

---

## 11. Vector Index — Current & Future

### 11.1 Current: FAISS, per-school

- One FAISS index per school, stored as a file on disk or blob storage.
- Loaded lazily into memory when a school's inference job arrives.
- LRU eviction policy if memory pressure builds across concurrent schools.
- Suitable for: up to ~50k students per school, hundreds of schools.

### 11.2 Future Migration Target: Milvus (preferred) or Qdrant

When to migrate (any one of):
- Total embeddings across all schools > ~5–10 million.
- Concurrent school jobs cause FAISS load/evict thrashing.
- Operational overhead of file-based per-school indices becomes painful.

**Why Milvus over Qdrant for this use case:**
- Native multi-tenancy via partitions — `school_id` maps cleanly to a partition key.
- Mature production deployments at scale.
- Qdrant is simpler ops but its partition / multi-tenancy story is weaker.

**Migration effort:**
- Implement `MilvusVectorIndex` against the same `VectorIndex` interface.
- Backfill script: iterate FAISS index files, bulk-insert into Milvus partitions keyed by `school_id`.
- No change required to orchestrator, enrollment API, or inference pipeline.

---

## 12. Configuration Surface

### Global defaults (env / config file)
- `default_match_confidence_threshold` — e.g. `0.65`
- `default_gap_threshold` — e.g. `0.08`
- `video_sample_fps` — e.g. `1.0`
- `top_k` — e.g. `2`
- `detector_impl` — adapter name (e.g. `retinaface`)
- `embedder_impl` — adapter name (e.g. `arcface`)
- `vector_index_impl` — adapter name (`faiss` for now)
- `media_store_impl` — adapter name (`azure_blob`, `s3`, etc.)
- `match_repo_impl` — adapter name

### Per-school (DB)
- `match_confidence_threshold` — nullable, overrides default
- `gap_threshold` — nullable, overrides default

---

## 13. Observability Requirements

Per inference job, emit:
- `faces_detected_total`
- `candidates_above_threshold_total`
- `matches_emitted_total`
- `ambiguous_matches_total` (records with `needs_review=true`)
- `unknown_faces_total`
- `frames_processed_total` (video)
- `processing_latency_ms` end-to-end
- `model_versions` (detector + embedder, as labels)

---

## 14. Open / Deferred Items

These are explicitly out of scope for v1 and tracked for later:

1. **Re-enrollment cadence.** Children's facial features change; embeddings may need refresh on a schedule.
2. **Privacy / legal.** DPDP Act (India), COPPA-equivalents. Affects embedding retention, consent capture, deletion guarantees.
3. **Manual review workflow.** UI and process for resolving `needs_review=true` matches.
4. **Unknown face handling.** Currently logged only; future may store for later review.
5. **Quality gating on reference photos.** v1 picks the largest face; future may add blur / pose / lighting checks.
6. **Video keyframe strategy.** v1 uses fixed FPS; future may switch to scene-change detection.

---

## 15. Acceptance Criteria for v1

The ML service is considered complete when:

- [ ] Enrollment API accepts `school_id` + `student_id` + photos and stores embeddings in the per-school FAISS index.
- [ ] Inference jobs can be enqueued and processed asynchronously.
- [ ] Inference correctly applies per-school threshold and gap logic.
- [ ] Match records are written with all required versioning fields.
- [ ] Re-processing the same `media_id` does not create duplicate rows.
- [ ] Swapping the embedder implementation (config change) does not require modifying orchestrator code.
- [ ] Swapping the media store (config change) does not require modifying orchestrator code.
- [ ] All locked decisions in Section 8 are reflected in code.
- [ ] Observability metrics from Section 13 are emitted.

---

## 16. Inputs Ready for Architecture Phase

Hand this document to the architecture specialist with these expectations:

1. Component diagram showing orchestrator, adapters, queue, vector index, repository.
2. Sequence diagrams for **enrollment** and **inference** flows.
3. Deployment view (workers, queue, storage, DB).
4. Concrete folder / module structure mapping to interfaces in Section 9.
5. Recommended initial adapter choices (specific OSS library versions) for detector and embedder.
6. FAISS index lifecycle plan (load, persist, evict, rebuild on enrollment update).
