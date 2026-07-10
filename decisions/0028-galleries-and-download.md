# 0028 — Galleries (two views + browse-all) + download (Phase 6)

**Date:** 2026-07-10
**Status:** Accepted

## Context

Phases 1–5 built the write side: onboarding, students + ML enrollment, events,
media upload, and event-level inference whose **status** the backend reads off its
own `events`/`media` rows (the ML worker writes those columns — [0027](0027-events-media-enqueue-status.md)).
What is missing is the *distribution UX* the whole product exists for: once an event
is processed, show each student the photos they appear in, let staff browse by event
or by student, and let anyone download a photo they're entitled to.

The result **contents** — *which student appears in which media* — are written by the
ML service into the shared Postgres `matches` table (one row per `(media_id,
student_id)`, indexed `(school_id,event_id)` and `(school_id,student_id)`;
[0012](0012-db-schema-and-alembic.md)/[0021](0021-persist-per-frame-detections.md)).
The backend reads them directly, scoped by `school_id`, per the locked fork
([0022](0022-backend-architecture-and-scope.md) decision #2). This is the **first**
backend read of an ML-owned table, so it also stands up the isolation module the
architecture reserved for it (`db/ml_read.py` + a `MlResultsReader` port).

## Decisions

### The read coupling is one port + one table module

- **`db/ml_read.py`** — a read-only SQLAlchemy Core `Table("matches", …)` on its
  **own** `MetaData()`, **not** registered in the backend `Base.metadata` (so backend
  Alembic never manages or migrates it). It declares **only the columns we consume**:
  `school_id, event_id, student_id, media_id, confidence_score, needs_review`
  (+ `match_id` for stable ordering). This is the single point where the backend
  knows the ML result-schema shape.
- **`MlResultsReader` port** (`domain/ports.py`) with **three** school-scoped reads,
  each one indexed query, returning the pure `Appearance` value object
  (`student_id, media_id, event_id, confidence, needs_review`):
  - `list_event_appearances(school_id, event_id)` — every match in an event (drives
    event→students **and** event→student→photos from one query).
  - `list_student_appearances(school_id, student_id)` — every match for a student
    (drives student→events **and** student→photos from one query).
  - `list_media_appearances(school_id, media_id)` — who appears in one photo (drives
    the appearances endpoint **and** the student-download entitlement check).
- Adapter `adapters/repositories/ml_results.py` (`PostgresMlResultsReader`), selected
  by the existing `repository_impl` selector (Postgres-only, like every repo). A
  **Phase-7 `information_schema` contract test** ([0022](0022-backend-architecture-and-scope.md))
  will assert these columns still exist, so an ML migration that drops/renames one
  fails backend CI loudly rather than at runtime.

Names, dates, and photo metadata are **not** read from `matches` — the reader returns
only join keys + the two decision facts (`confidence`, `needs_review`); the
`GalleryService` joins those against the **backend-owned** `students`/`events`/`media`
rows for all display data. `matches` stays a pure "who-is-where" index.

### `GalleryService` joins ML facts to backend rows; grouping is in-service

The service resolves each view by pairing reader `Appearance`s with backend repos:

- **event→students**: `list_event_appearances` → group by `student_id`, `count = #media` →
  iterate the school's **ordered** student roster (`students.list_by_school`) filtering
  to the appearing set (deterministic order for free) → `[(Student, media_count)]`.
- **event→student→photos**: `list_event_appearances` filtered to the student → media_ids →
  `media.list_by_ids` (new, ordered) → `[Media]`.
- **student→events**: `list_student_appearances` → group by `event_id`, `count = #media` →
  iterate `events.list_by_school` filtered to the appearing set → `[(Event, media_count)]`.
- **student→photos**: `list_student_appearances` (optionally filtered to one `event_id`) →
  `media.list_by_ids` → `[Media]`.
- **media→appearances**: `list_media_appearances` → join students for names →
  `[(Student, confidence, needs_review)]`.

Grouping/filtering in Python (not SQL `GROUP BY`) is deliberate for v1: a school event
is bounded (hundreds of photos, hundreds of students), the queries are single indexed
scans, and it keeps the reader port at three simple methods. Materializing
student→events ([0022](0022-backend-architecture-and-scope.md)) stays deferred until
profiling justifies it.

Existence is verified for clean tenant 404s (foreign/missing `event_id`/`student_id`/
`media_id` → `NotFoundError` → 404), reusing the backend repos' tenant scoping.

**Browse-all** (every photo in an event, regardless of who's in it) is **already
served** by `GET /v1/events/{id}/media` (Phase 5) — not duplicated here.

### Two role surfaces, one service

Gallery reads split by role via the already-seeded permissions
([0024](0024-auth-jwt-and-rbac.md)): `GALLERY_VIEW_ALL` (school_admin + teacher) vs
`GALLERY_VIEW_OWN` (student). The service methods are role-agnostic (they take
`school_id` + ids); the **routes** supply the ids and the scope:

- **Staff routes** (`GALLERY_VIEW_ALL`, tenant from the token):
  `GET /v1/events/{event_id}/students`,
  `GET /v1/events/{event_id}/students/{student_id}/media`,
  `GET /v1/students/{student_id}/events`,
  `GET /v1/students/{student_id}/media?event_id=`,
  `GET /v1/media/{media_id}/appearances`.
- **Student self routes** (`GALLERY_VIEW_OWN`; the caller's `student_id` is resolved
  from the token, never supplied): `GET /v1/me/events`, `GET /v1/me/media?event_id=`.
  These reuse `student_events`/`student_media` with the caller's own id.

Resolving a logged-in student to their `student_id` needs a new tenant-scoped
`StudentRepository.get_by_user_id(school_id, user_id)`. (No `user_id` index is added
in this phase — the lookup is once per student session; an index is deferred to Phase
7 hardening. Phase 6 ships **no migration** — it is pure reads.)

### Download = short-lived signed URL, entitlement-checked

- `ObjectStore` gains `create_signed_download_url(object_path, *, expires_in_s) -> str`.
  The **supabase** adapter calls `create_signed_url(path, ttl)` (off-thread, errors →
  `UpstreamError`→502); the **local_fs** dev stub returns a deterministic `file://`
  URL (no real signing), mirroring the upload stub. New setting
  `BE_DOWNLOAD_URL_TTL_S` (default 3600).
- `GET /v1/media/{media_id}/download` → `{download_url, expires_in_s}`. Authz is
  data-dependent, so it uses a `GalleryScope` dep (`school_id` +
  `restrict_to_student_id`): a caller with `GALLERY_VIEW_ALL` downloads **any** media
  in their school; a caller with `GALLERY_VIEW_OWN` may download **only** media they
  appear in (checked via `list_media_appearances`). A student requesting a media they
  don't appear in gets **404** (not 403) so the endpoint never confirms the existence
  of a photo they're not entitled to see. The bytes never transit the backend.

Gallery **list** endpoints return media **metadata** only (`media_id, event_id,
media_type`) — a lean `GalleryMediaResponse` that omits the internal `storage_path`;
the FE lazily calls the download endpoint per photo when it needs to render/fetch it.
This avoids minting N signed URLs to build one list; batch-signing is a documented
scale follow-up.

### Wiring / surface

- `ML_RESULTS_READER_REGISTRY` (postgres) in `wiring/registry.py`; `ml_results_reader()`
  + `gallery_service()` in the container; `galleries`/`me` routers mounted in `main.py`.
- New ports/methods: `MlResultsReader`; `ObjectStore.create_signed_download_url`;
  `StudentRepository.get_by_user_id`; `MediaRepository.list_by_ids`.
- New domain value types: `Appearance`, `SignedDownload`.

## Consequences

- The product's core UX is reachable: both views, browse-all (existing), per-photo
  appearances, student self-scope, and entitlement-gated download.
- The **only** coupling to the ML result schema is `db/ml_read.py` + the reader
  adapter, over six named columns of `matches`, CI-guarded in Phase 7. `domain`/
  `services` stay import-pure (the layering grep is unaffected — `ml_read.py` lives
  under `db/`).
- **No migration, no ML-service change** — Phase 6 reads existing tables the ML
  service already writes.
- The `matches`-based views assume detection populated `matches`; an unprocessed or
  zero-student photo simply doesn't appear in any student/appearance view (and a
  student can't download it) — correct.

## Alternatives rejected

- **Read the `student_media_appearances` view for the galleries** — rejected for v1:
  the view is per-frame (multiple rows per media) and carries no more identity than
  `matches`; `matches` is already the deduped one-row-per-`(media,student)` answer the
  galleries want. The view stays reserved for post-v1 in-photo bounding boxes.
- **`GROUP BY`/aggregate in SQL** — rejected at v1 scale in favour of three simple
  single-scan reads + in-service grouping (fewer reader methods, simpler tests);
  revisit under profiling.
- **Inline a signed URL in every gallery item** — rejected: N signing round-trips to
  render one list; lazy per-photo download is cheaper and cache-friendly.
- **A backend `matches` mirror/sync table** — rejected again ([0022](0022-backend-architecture-and-scope.md)):
  a write path + drift risk for no benefit at this scale.
