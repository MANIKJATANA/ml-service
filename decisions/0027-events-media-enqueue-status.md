# 0027 — Events, media upload, event-level processing + status (Phase 5)

**Date:** 2026-07-10
**Status:** Accepted (revised **twice** after owner review — see the revision notes)

## Context

Phase 4 ([0026](0026-students-and-ml-enrollment.md)) landed students + synchronous ML
**enrollment** (HTTP). Phase 5 opens the **async inference** half — distributing an
event's photos to the students who appear in them.

> **Revision note.** The first draft of this doc enqueued **one ML job per photo at
> upload time** and inferred completion from a per-photo `media_detections` row. On owner
> review that was rejected: **uploading a photo must not trigger anything**, and
> processing must be **event-level** — one explicit action processes the *whole event at
> once*, not per photo. This revision replaces that design. It deliberately overrides
> three invariants locked earlier and does so **with owner sign-off**: (a) "no ML
> changes" ([0022](0022-backend-architecture-and-scope.md)) — the ML worker gains an
> event-level path; (b) "ML never reads the backend" — ML now reads the backend `media`
> roster from the shared DB; (c) the per-photo inference-job contract — the queue now
> carries event jobs. The two ML specs (`ml-service-requirements.md` /
> `ml-service-architecture.md`) describe per-media inference triggering and must be
> updated to match; that update is part of this phase.

> **Revision note 2 (status: ML-written, no poller).** The second draft used a backend
> **poller** that derived the event/photo status by reading ML's `media_detections`
> table each tick. On owner review that was rejected as over-complex ("why check 1000
> media rows for one job's status?"). Final design: the **ML worker writes the status
> columns directly** on the backend's own `events`/`media` rows over the shared DB —
> event `processing` on pickup, `completed` when done; each photo `completed` as it
> finishes — and the backend just **reads its own row** (one DB call). This removes the
> backend poller, the `MlResultsReader`/`db/ml_read.py` completion read, and the
> `media_detections`-presence signal entirely. The coupling reverses further **with owner
> sign-off**: ML now also *writes* two backend-owned status columns (the string values are
> a contract with the backend's CHECK constraints). `media_detections` is still written by
> ML as the detection audit (it feeds Phase-6 galleries), just not used for status. The
> flow/decisions below reflect this final design.

## The corrected flow (owner-locked)

1. **Upload just records.** The frontend uploads each photo to Supabase (under the
   event's prefix) and registers it; the backend creates a `media` row with status
   `pending`. **No queue, no enqueue, no compensating delete** — recording a photo
   triggers nothing.
2. **One "Process" action per event.** A single button calls
   `POST /v1/events/{event_id}/process`, sending only `{event_id}` (school from the
   token, **never photos**). The backend enqueues **one event job** `{school_id,
   event_id}` and sets the **event** status to `queued` — but **only if the event is not
   already `queued`/`processing`** (an in-flight event is never XADD'd twice; a stuck one
   is recovered by the queue's `XAUTOCLAIM` reclaim, not a manual re-add). Pressing it
   again (**"redistribute"**) therefore applies once a run has `completed` but some photos
   stayed `pending` (e.g. a fetch error): it re-enqueues, and the ML worker skips the
   already-`completed` photos, so only the leftovers are re-done — idempotent.
3. **ML processes the whole event and writes the status.** The ML worker consumes the
   event job, sets the backend event row to `processing`, **reads the backend `media`
   roster** for that event from the shared DB (getting each real `media_id` + storage
   path + its status), **skips any photo already `completed`**, runs the existing per-photo
   detect→embed→search→decide pipeline on the rest (writing `matches` + `media_detections`
   per `media_id` as today), marks each finished photo `completed` on its backend `media`
   row, and finally sets the event row to `completed`.
4. **The backend just reads its own rows (no poller):**
   - **Per-photo** status is a column on the backend `media` row, flipped `pending →
     completed` **by the ML worker** as it finishes each photo.
   - **Event** status is the single value the FE reads in one DB call:
     `not_started → queued` (backend, on Process) `→ processing → completed` (ML, on
     pickup / finish). No derivation, no counting, no `media_detections`-presence read.

## Decisions

### Why the event job carries only `{school_id, event_id}` and ML reads the roster

The owner ruled the job must **not** carry the photo list. ML instead learns the event's
photos by **reading the backend `media` table directly from the shared Postgres**
(read-only), the mirror of how the backend already reads ML's `media_detections`
([0022](0022-backend-architecture-and-scope.md)). Chosen over a **backend HTTP API that
ML calls** because a shared-DB read keeps the services **runtime-decoupled** (ML does not
depend on the backend being reachable), is lighter, and matches the existing
coupling direction. The coupling is contained to **one read-only module on each side**
(`backend/db/ml_read.py` already; a new `ml_service/db/backend_read.py` mirror) and is
guarded by the Phase-7 `information_schema` contract test on **both** directions.

Media-id integrity is trivial: ML reads the backend's real `media_id`, so `matches`/
`media_detections` are keyed correctly with no object-key-encoding tricks.

### New tables/models (migration `0004`)

`events` (new column vs. the first draft): add `processing_status` (event-level).

| column | type | notes |
|---|---|---|
| `id` | uuid PK | string form = ML `event_id` |
| `school_id` | uuid NOT NULL FK `schools.id` CASCADE | tenant |
| `name` / `description` / `event_date` | text / text / date | metadata |
| `created_by` | uuid NULL FK `users.id` SET NULL | outlives its creator |
| `status` | text NOT NULL `'active'` | `active`/`archived` (lifecycle) |
| `processing_status` | text NOT NULL `'not_started'` | `not_started`/`queued`/`processing`/`completed`/`failed` |
| `enqueued_at` / `completed_at` | timestamptz NULL | set on process / when all done |
| `created_at` / `updated_at` | timestamptz | server defaults |

`media`:

| column | type | notes |
|---|---|---|
| `id` | uuid PK | string form = ML `media_id` |
| `school_id` | uuid NOT NULL FK `schools.id` CASCADE | tenant |
| `event_id` | uuid NOT NULL FK `events.id` CASCADE | parent |
| `storage_path` | text NOT NULL | bucket-relative = ML `media_uri` |
| `media_type` | text NOT NULL | `image`/`video` |
| `processing_status` | text NOT NULL `'pending'` | `pending`/`completed` (per-photo, **written by ML**) |
| `completed_at` | timestamptz NULL | stamped by ML when it finishes the photo |
| `created_at` / `updated_at` | timestamptz | server defaults |
| indexes | `ix_media_event (school_id, event_id)`, `ix_media_status (processing_status)` | listing; roster |

Per-photo status is only `pending → completed` (a photo is never individually queued or
failed — one that never finishes just stays `pending`, and a redistribute re-runs it).
Event `processing_status` is `not_started/queued/processing/completed`. All CHECK lists
stay in lockstep with the domain enums (`EventStatus`, `EventProcessingStatus`,
`MediaType`, `MediaProcessingStatus`).

### Backend ports + services

- **`EventRepository`** — create/get/list/update + `set_processing(event_id, *, status)`.
  The backend only ever calls it with `queued` (on Process; stamps `enqueued_at`, clears
  `completed_at`) — the **ML worker owns the `processing`/`completed` writes**.
- **`MediaRepository`** — create (status `pending`) / get / list_by_event /
  `status_counts`. Read-only over the per-photo status column (the ML worker writes it).
- **`EventJobProducer`** — `enqueue(EventJob{school_id, event_id})`; `redis` (XADD the
  two string fields) + `inproc`. Unreachable → `UpstreamError`→502.
- **`EventService`** — event CRUD + **`process_event(school_id, event_id)`**: verify the
  event is the caller's + `active`, **not already `queued`/`processing`** (else
  `ValidationError` — no duplicate enqueue), and has ≥1 `pending` photo (else
  `ValidationError`); enqueue the event job; set `processing_status=queued`. Redistribute
  (a re-press once the event is `completed` with leftover `pending` photos) is idempotent
  since the ML worker skips `completed` photos. (App-layer guard; the single-writer-per-
  school race is accepted as in 0025/0026, and ML idempotency backstops it.)
- **`MediaService`** — upload-url + `register_media` (records `pending`, **no enqueue**),
  reads.
- **No poller.** There is no `JobStatusService`, `MlResultsReader`, or `db/ml_read.py` in
  this phase — job status is read straight off the backend's own `events`/`media` rows,
  which the ML worker writes.

### ML-service changes (this phase, per owner "do both now")

- **Event-job consumer.** The inference queue now carries `{school_id, event_id}` (the
  worker's decoder + `InferenceService` gain a `process_event` path). The per-photo job
  shape is removed.
- **`BackendEventStore` port + adapter** — reads the backend `media` roster for an event
  **and writes the backend status columns** over the shared DB (`db/backend_tables.py`,
  its own `MetaData`, never in the ML `Base`): `list_event_media`, `mark_media_completed`,
  `mark_event_processing`, `mark_event_completed`. The written string values are a contract
  with the backend's CHECK constraints.
- **Worker loop.** On an event job: `mark_event_processing`; read the roster; for each
  photo **not already `completed`**, run the existing per-photo `InferenceService` path
  (unchanged detect/embed/search/decide + `matches`/`media_detections` writes) then
  `mark_media_completed`; finally `mark_event_completed`. Idempotent, so redistribute
  safely re-runs only the leftovers.
- No change to enrollment, the FAISS lifecycle, or the decision logic.

### Routes (tenant from token)

| Method + path | Permission | Purpose |
|---|---|---|
| `POST /v1/events` · `GET /v1/events` · `GET/PATCH /v1/events/{id}` | `event:manage` | event CRUD (archive, not delete) |
| `POST /v1/events/{id}/media/upload-url` | `media:upload` | signed media upload URL |
| `POST /v1/events/{id}/media` | `media:upload` | **register** media (records `pending`; no enqueue) |
| `POST /v1/events/{id}/process` | `media:upload` | enqueue the event job / **redistribute** leftovers |
| `GET /v1/events/{id}/media` | `job:status:view` | list media + per-photo status |
| `GET /v1/events/{id}/status` | `job:status:view` | event `processing_status` + per-photo `{pending,completed,total}` |
| `GET /v1/media/{id}` | `job:status:view` | one photo's status |

### Settings + env surface

New/changed `BE_`: `event_job_producer_impl` (`redis`/`inproc`), `redis_url`,
`queue_stream` (== `ML_QUEUE_STREAM`; now event jobs), `event_media_prefix`. New dep
`redis>=5`. No poller knobs (no poller). ML side reuses `ML_DATABASE_URL` for the
backend-roster read+write (same DB), selected by `ML_BACKEND_EVENT_STORE_IMPL`.

## Consequences

- Uploading is side-effect-free; processing is one explicit, idempotent, event-level
  action that safely re-runs leftovers. The FE gets one event status to poll and per-photo
  status in the DB.
- The two services stay **runtime-decoupled** (shared DB, no cross-HTTP); the new coupling
  is a roster read + the status writes on the backend's own rows.
- The ML specs must be updated to describe event-level inference triggering (tracked in
  this phase).

**Accepted tradeoffs (no poller / no timeout):**

- A photo that errors mid-run (fetch/decode) is **skipped and stays `pending`**, yet the
  event still finishes as `completed`. So `completed` event + `pending > 0` per-photo count
  means "done, but N photos couldn't be processed — press Process again to retry them." The
  FE should read it that way. (There is no per-photo error state in v1; a permanently-bad
  photo looks like a not-yet-done one and is retried by redistribute.)
- If the worker **dies mid-event**, the event stays `processing` (never a false
  `completed` — that's only written after the loop). Recovery is the queue's pending-entry
  reclaim (`XAUTOCLAIM`) or a manual redistribute; there is no automatic timeout reaper.
- Two workers on the **same** event (redelivery before the first finishes) is safe — all
  writes are idempotent single-statement `UPDATE`s and the per-photo work is idempotent —
  though one worker's `mark_event_completed` can briefly land while the other is still
  finishing photos. Harmless (the leftover photos are already `completed` or get retried).

## Alternatives rejected

- **Per-photo enqueue at upload** (the first draft) — rejected by the owner: uploading
  must not trigger work; processing is event-level and explicit.
- **Photo list inside the event job** — rejected by the owner: the job carries only
  `{school_id, event_id}`.
- **A backend HTTP API for ML to fetch the roster / report status** — rejected in favour
  of the shared-DB read+write: keeps ML from depending on the backend being up, and matches
  the existing backend↔ML shared-DB coupling.
- **A backend poller deriving status from `media_detections` presence** (revision 2's
  design) — rejected by the owner as over-complex: it re-reads N media rows per event each
  tick to compute one status. The ML worker instead **writes** the event/media status
  directly (one write per photo + two per event), and the backend reads one row. This
  reverses "each service writes only its own tables" — accepted with owner sign-off for the
  simplicity; the status string values are a documented cross-service contract.
- **A distinct event "picked-up" vs "processing" split** — not needed: the ML worker sets
  `processing` on pickup (before any photo finishes), so the FE already sees it the moment
  the job is claimed.
