# 0021 — Persist the full per-face detection audit (media-centric) + a student view

Date: 2026-07-07

## Context

[decisions/0020](0020-identify-all-faces-and-per-frame.md) made identification
`face → person` and had the shared `identify_in_frames` kernel return the full
per-frame / per-face timeline, but **persisting** that timeline was deferred — the
worker still wrote only the deduped `matches` summary (one row per
`(media_id, student_id)`).

The requirement now: at detection time, persist **everything useful**, in two
complementary views —

- **Detection = media-centric**: the image/video → *what it consists of and how each
  identity was determined*. Every detected face (matched or not), every sampled frame,
  each face's raw top-k candidates with scores, and the `top_k` / thresholds / model
  versions used.
- **Matches = student-centric**: keyed on `(student_id, media_id)` → *is this student
  present, and where* (all their frames + boxes).

A design review (recorded in `services/ml_service/docs/05-data-model.md`) validated the
split and surfaced additions; two forks were resolved with the user: **don't store face
embeddings** (re-derivable, heavy), and **don't copy appearances onto `matches`** —
expose them via a derived view (single source, no drift).

## Decision

Add a media-centric detection hierarchy (migration `0002`), a small `matches` addition,
and a derived view. `matches` keeps its locked one-row-per-`(media_id, student_id)` +
higher-confidence-wins contract (NFR-5) unchanged — the new tables are purely additive.

### Schema (migration `0002`, mirrored in `db/models.py`)

- **`media_detections`** — one row per processed media: media summary + the counts from
  `JobOutcome` (`faces_detected`, `candidates_above_threshold`, `unknown_faces`,
  `matches_emitted`, `ambiguous_matches`), `frames_sampled`, `video_fps`, `top_k`,
  thresholds, model versions, `processing_ms`. Unique `(media_id)`.
- **`media_frames`** — one row per sampled frame (records empty frames too). FK →
  `media_detections` `ON DELETE CASCADE`.
- **`face_detections`** — one row per detected face, **including unknowns**
  (`outcome ∈ {unknown, match, ambiguous}`); `bbox`, `detection_score`, and `landmarks`
  (the box's 5-point landmarks, previously dropped). FKs → media + frame, cascade.
- **`face_detection_candidates`** — one row per raw top-k hit
  (`student_id, score, rank, cleared_threshold, emitted, needs_review`), incl.
  below-threshold hits and the closest-but-missed on an unknown face. FK → face, cascade.
- **`matches`** gains **`frames_matched`** (how many frames the student was emitted in).
- **`student_media_appearances`** — a **view** over the emitted candidates ⋈ faces ⋈
  media, giving "student X → all their frames + boxes" without duplicating data.

### Code

- **Kernel** (`orchestration/identify.py`): `FaceResult` gains `candidates:
  list[Candidate]` — the raw search result, previously discarded after the decision. Pure
  (a `Candidate` is a domain type), so no layering change; behaviour of `people` /
  counters is unchanged.
- **`InferenceService`** builds a `MediaDetectionRecord` tree from `result.frames`
  (flagging each candidate `cleared_threshold`/`emitted`/`needs_review`, deriving
  `outcome` and per-student `frames_matched`) and persists it via a new
  `DetectionRepository` — **the 10th port** — after the `matches` write. Gated by a
  `persist_detections` flag (default on; `ML_PERSIST_DETECTIONS`).
- **`PostgresDetectionRepository`**: **replace-by-media** — a per-`media_id`
  `pg_advisory_xact_lock` (serializes concurrent reprocessing), then delete on
  `media_detections` (FK cascade wipes the tree) + bulk insert, in one transaction.

### Two idempotency models

`matches` = **higher-confidence-wins** upsert (may skip a lower reprocess); detection =
**replace-by-media** (always the latest pass). Because they can reflect different passes,
appearances are **derived** (the view), never copied onto `matches`. The two writes run
in **separate transactions**, each independently idempotent, so a partial failure
self-heals on the worker's retry (no cross-repo transaction).

## Not stored (recorded non-goals)

- **Face embeddings** (512-d query vectors) — re-derivable from the retained media +
  stamped versions, and too voluminous per face per frame. Documented opt-in `pgvector`
  path if ever needed.
- **Frame width/height** — not exposed by the domain `Frame`; would need a small domain
  change to enable normalized/renderable boxes. Deferred.

## Divergences from the locked spec (surfaced per the working rules)

- Extends the locked `matches` contract (req §10.1): adds `frames_matched`
  (backward-compatible; NFR-5 higher-wins unchanged).
- Executes **and expands** 0020's deferred per-frame persistence (which the spec listed
  as one deduped row per `(media_id, student_id)`).
- Introduces a **second idempotency model** (replace-by-media) alongside the locked
  higher-wins, plus a `pg_advisory_xact_lock`.
- Persists §13 metric counts (previously observability-only) and, newly, unknown faces
  (FR-I8 only logged them).

## Notes / rejected

- **Copying appearances onto `matches`** (a jsonb column or a child table) — rejected:
  duplicates the detection evidence and would drift under the two idempotency models. The
  derived view answers the student-centric question with no second copy.
- **A single cross-repo transaction** for matches + detections — not done; both paths are
  idempotent, so retry self-heals. A shared unit-of-work is a documented future option.
- **Storing embeddings** — declined (above), to keep it on record.
- Amends/implements [0020]; supersedes its "deferred" status for per-frame persistence.
