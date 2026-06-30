# Pipelines

Two independent flows share one embedding-model version. Both are driven by the
same `orchestration/` services; in later phases the API and worker are thin
shells that build a context and call these services.

## Enrollment (synchronous, student-id-triggered)

The frontend uploads a reference image directly to storage; the backend records
its URL. For **enroll or refresh** the backend sends the `student_id`; the ML
service resolves that student's reference-photo URI(s) from its own table and
fetches the bytes via `MediaStore` (Supabase Storage by default). See
[decisions/0009](../../../decisions/0009-enrollment-contract.md).

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant ST as Supabase Storage
    participant BE as Backend (core)
    participant API as ML API
    participant ES as EnrollmentService
    participant RP as ReferencePhotoRepository
    participant MS as MediaStore
    participant DT as FaceDetector
    participant EM as FaceEmbedder
    participant VI as VectorIndex (faiss)

    FE->>ST: upload image
    FE->>BE: notify (image URL)
    BE->>API: POST /v1/schools/{sid}/students/{stid}/enroll {photo_uris?}
    API->>ES: enroll(sid, stid, photo_uris?)
    alt photo_uris provided
        ES->>RP: replace(sid, stid, photo_uris)
    end
    ES->>RP: get(sid, stid) -> uris
    loop each uri  (per-photo failure isolated, FR-E4)
        ES->>MS: fetch(uri)
        ES->>DT: detect(bytes)
        Note over ES: pick largest face (log warn if >1, req §8.7)
        ES->>EM: embed(bytes, box)
    end
    ES->>VI: upsert(sid, stid, embeddings, meta)
    Note over VI: atomic replace (FR-E3); skipped if no embeddings
    ES-->>API: EnrollmentResult (per-photo statuses)
    API-->>BE: 200
```

Invariants:
- **Per-photo isolation (FR-E4):** a fetch/detect/embed failure on one photo is recorded as `ERROR` and does not abort the others.
- **Replace-not-append (FR-E3):** all valid embeddings are upserted in one call; if *every* photo fails, no upsert runs (prior embeddings are never wiped).
- **Pick largest (req §8.7):** multiple faces in one photo → the largest box is embedded and the photo is flagged `MULTIPLE_FACES`.
- **Refresh:** calling `enroll` with no `photo_uris` re-embeds the URIs already stored for the student.
- **Empty list rejected:** an explicit `photo_uris=[]` is rejected with `EnrollmentError` (clearing a student is `delete()`'s job, not enrollment's); stored URIs are left untouched.
- **De-dup (order-preserving):** the resolved URIs are de-duplicated preserving first-seen order, so the same photo is never embedded twice.

## Inference (asynchronous, queue-driven)

```mermaid
sequenceDiagram
    participant BE as Backend
    participant Q as Redis Streams
    participant W as Worker
    participant IS as InferenceService
    participant MS as MediaStore
    participant TP as ThresholdProvider
    participant VX as VideoFrameExtractor
    participant DT as FaceDetector
    participant EM as FaceEmbedder
    participant VI as VectorIndex
    participant MR as MatchRepository

    BE->>Q: enqueue(job)
    W->>Q: consume -> lease
    W->>IS: process(job)
    IS->>MS: fetch(media_uri)
    IS->>TP: get_thresholds(school_id)
    Note over IS: resolved ONCE per job; passed by value
    opt media_type == video
        IS->>VX: extract(bytes, fps)
    end
    loop each frame -> each detected face
        IS->>DT: detect(frame)
        IS->>EM: embed(frame, box)
        IS->>VI: search(school_id, emb, top_k)
        Note over IS: apply_threshold_and_gap (§6.2)<br/>dedupe (student_id, media_id), keep best score
    end
    IS->>MR: save_batch(records)
    Note over MR: only write path; INSERT..ON CONFLICT, higher confidence wins
    IS-->>W: JobOutcome
    W->>Q: ack(lease)
```

Invariants:
- **Thresholds once per job** (not per face), captured in context and passed to the pure decision function.
- **Version snapshot (NFR-4):** `detector.version` and `embedder.version` are read once at job start and stamped on every record, along with `threshold_used`/`gap_threshold_used`.
- **In-memory dedupe (FR-I6):** detections are buffered by `(student_id, media_id)` keeping the highest-confidence hit and its bbox/frame timestamp; the DB unique key `(media_id, student_id)` is the second line of defence (NFR-5).
- **Tenant isolation (FR-I4/NFR-3):** every `search` is scoped to `job.school_id`.
- **Config validated at construction:** `InferenceService` rejects `top_k < 2` (the gap decision needs two candidates) and `video_fps <= 0` with `ConfigurationError`.
- **`save_batch` is the only write path** — and is skipped entirely when there are zero records.

## `JobOutcome` → metrics (req §13)

`InferenceService.process` returns a `JobOutcome` instead of emitting metrics
itself (keeping orchestration import-pure). The Phase-4 worker maps it to the
required counters:

| `JobOutcome` field | Metric (req §13) |
|---|---|
| `faces_detected` | `faces_detected_total` |
| `candidates_above_threshold` | `candidates_above_threshold_total` (counts **distinct** students above threshold, not raw candidate rows) |
| `matches_emitted` | `matches_emitted_total` |
| `ambiguous_matches` | `ambiguous_matches_total` |
| `unknown_faces` | `unknown_faces_total` |
| `frames_processed` | `frames_processed_total` (video) |
| `detector_version`, `embedding_model_version` | metric labels |

End-to-end latency is measured by the worker around `process`.
