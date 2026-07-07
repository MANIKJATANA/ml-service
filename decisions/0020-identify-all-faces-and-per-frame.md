# 0020 — Identify every face (face → person); per-frame detail via a shared kernel

Date: 2026-07-07

> **Per-frame persistence implemented by [0021](0021-persist-per-frame-detections.md).**
> The "designed for, deferred" section below is now built: the `media_detections` /
> `media_frames` / `face_detections` / `face_detection_candidates` tables + the
> `student_media_appearances` view, and the kernel's `FaceResult` now carries the raw
> candidates so the audit is complete.

## Context

Identification's unit of work is **`face → person`**, not `image → person`. One
image can hold many faces (many people); one video frame can hold several people;
and across a video the same person recurs in many frames. The requirement is to
name **every** detected face, and — for video — to report results **per sampled
frame (timestamp)**: which faces are in that frame and who each is, *not* a single
globally-deduped set of people.

The real inference worker was already correct for what it **persists**: it loops
every frame and every face, decides per face, and dedupes on `(student_id,
media_id)` keeping the highest confidence (the locked `matches` idempotency
contract, NFR-5). But two gaps remained:

1. The dev **test UI** (`api/routes/dev_ui.py`, decisions/0019) identified only the
   **largest** face per image (`box = max(boxes, key=area)`) — an `image → person`
   view. A group photo returned one name; it did not accept video at all.
2. There was no reusable expression of the per-frame/per-face result, so the test
   UI and the worker risked drifting, and a future "persist per-frame appearances"
   feature would have to re-implement the loop.

## Decision

Extract the per-media identify loop into a single shared kernel and have both the
worker and the test UI call it.

- **New `orchestration/identify.py`** — `identify_in_frames(frames, *, school_id,
  detector, embedder, index, thresholds, top_k) -> IdentifyResult`. Pure
  orchestration (imports only `domain`). It returns **two views of one pass**:
  - `frames: list[FrameResult]` — the full **per-frame / per-face** timeline. Each
    `FrameResult` has its `frame_timestamp_ms` (None for a still image) and its
    `faces`; each `FaceResult` has the face `bbox` and its `people`
    (`list[PersonHit]`: 0 = unknown, 1 = match, 2 = ambiguous with `needs_review`).
  - `people: dict[str, PersonHit]` — the media collapsed to the **best hit per
    student**, reproducing the worker's `(student_id, media_id)` dedupe exactly
    (media_id is constant within a job).
  - Plus the counters (`faces_detected`, `candidates_above_threshold`,
    `unknown_faces`, `frames_processed`) the worker needs for `JobOutcome`.

- **`InferenceService.process` now calls the kernel** and maps `result.people` →
  `MatchRecord`s. Behaviour is unchanged — the deduped-per-media `matches` write
  stays the locked contract (NFR-5). `result.frames` is available but unused by the
  worker for now (see below).

- **Test UI (`dev_ui.py`) reworked** to identify **every** face via the kernel and
  to accept **images and video**:
  - Media type is inferred from the upload's content-type / extension. Images run as
    a single `Frame`; videos are sampled at `video_sample_fps` via the configured
    `VideoFrameExtractor` (materialized off the event loop in a threadpool).
  - `/v1/test/check` and `/v1/test/check-bulk` return the full shape (`media_type`,
    `faces_detected`, `frames_processed`, per-frame `frames[]`, and a deduped
    `people_summary`).
  - The page renders **per-face chips** for an image and a **per-timestamp timeline**
    for a video (`t=1.0s → alice, bob`), so a person in several frames shows at each
    of those timestamps.

## Per-frame persistence: designed for, deferred

Persisting per-frame appearances is a likely future need ("for now the test UI, but
we might need to persist per frame later"). This design makes it **purely additive**:
the kernel already emits `result.frames`, so the worker would only need to also write
those to a new `match_detections` table (`media_id, student_id, frame_timestamp_ms,
bbox, score`, via an Alembic migration) alongside the deduped `matches` summary. No
kernel or test-UI change required. Deferred now because it is a locked-spec divergence
(the spec's persisted output is one deduped row per `(media_id, student_id)`) and no
consumer needs it yet.

## Notes / rejected

- **Duplicating the loop in the test UI** (leaving the worker untouched) — rejected:
  the test UI's whole point is to show the *real* pipeline; a copy would drift.
- **Changing the `matches` schema now** — rejected/deferred: no consumer yet, and it
  diverges from the locked idempotency contract. Captured above as the additive path.
- The kernel takes **resolved `Thresholds`** (not the provider): thresholds are
  resolved once per job by the caller and passed by value (NFR-4); the kernel stays
  free of providers, repos, and the clock.
- Tests: `tests/unit/test_identify.py` pins the per-frame structure (timestamps, a
  person appearing in each frame yet once in `people`, multi-face, ambiguous,
  unknown); `tests/unit/test_inference_service.py` gains a multi-frame × multi-face ×
  multi-person case. `dev_ui.py` stays uncollected by pytest (needs real models).
- Amends decisions/0019 (the `_identify_image` largest-face helper is replaced).
