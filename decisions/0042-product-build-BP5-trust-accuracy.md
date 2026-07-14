# 0042 — Product Build BP5: Trust & accuracy loop

**Date:** 2026-07-14
**Status:** Accepted

## Context

The roadmap phase after BP1–BP4 (`product/03`). Today `needs_review` + the rich ML detection audit are **dead data** —
staff can *see* an ambiguous match's confidence but can't act on it, a student can't say "that isn't me," and a missed
student can't be added. Accuracy is frozen and there's no feedback loop (fails lens **X2**, target **T3**). BP5 turns
matching into a **correctable, trustworthy loop**. **Backend + frontend; one migration (`0006`); no ML change** —
corrections are a backend-owned overlay (the ML has no feedback loop and the backend never writes ML tables). Design
validated by a Plan agent; **large phase**, built BE-first then FE. Three owner decisions this session: (1) **reject →
hide + block download**; (2) students **self-serve "this isn't me"**; (3) **include report-a-miss** (staff add a missed
student). Threshold tuning is **out of scope** (ML-owned `school_thresholds`).

## Decisions

### 1. A backend-owned correction overlay keyed on `(media_id, student_id)` — no ML write, no cross-seam SQL
`matches` (ML-owned, read-only via `db/ml_read.py`) has `UNIQUE(media_id, student_id)` with higher-confidence-wins
re-inference, so **`match_id` churns but `(media_id, student_id)` is the stable identity.** A new backend table keys on
that — **no FK to the ML `matches`**. New `MatchCorrection` VO + `MatchVerdict` StrEnum `{confirmed, rejected, added}` +
a `MatchCorrectionRepository` port (`upsert`/`get`/`delete`/`list_for_{media,event,student}`/`count_resolved`) + a
Postgres adapter (upsert via `on_conflict_do_update` on `uq_match_corrections_pair`).

### 2. Migration `0006` — `match_corrections`
Mirrors `0005` (String enum + `CheckConstraint`, not native ENUM): `id` uuid pk; `school_id`/`media_id`/`student_id`/
`event_id` FKs (media/students/events CASCADE; `event_id` denormalized from `media.event_id`, safe since media→event is
immutable); `corrected_by` → `users.id` `SET NULL`; `verdict`; `reason` null; **`resolves_review`** bool default false
(true when the corrected match was `needs_review` at review time — for the dashboard count); `created_at`/`updated_at`;
`UNIQUE(media_id, student_id)` (upsert, latest verdict wins) + indexes `(school_id, {media,event,student})`.

### 3. The effective-appearance overlay (the security-sensitive core)
"Effective appearances of media M" = **(ML matches whose `(M, student)` verdict is NOT `rejected`) ∪ (`added`/
`confirmed` corrections)**. The reject predicate is **exactly `verdict == rejected`** — `confirmed`/`added`/no-correction
all mean "appears"; a `confirmed` stands even if a later re-inference drops the raw match (staff vouched for it). Three
pure helpers (`effective_media_student_ids`, `effective_event_pairs`, `effective_student_pairs`) live in
`gallery_service.py` and are shared (imported) by `ReviewService` **and** `NotificationService`. `GalleryService` gains
the correction-repo dep and applies the overlay to **all six reads** + the **download gate**, batched via
`list_for_{event,student}` (no N+1):
- `event_students`/`student_events` — effective set + `media_count` recomputed from the effective list.
- `event_student_media`/`student_media` — effective media only.
- `media_appearances` (staff photo detail, `gallery:view_all`) — **shows every match incl. rejected**, each carrying its
  `verdict` (+ nullable `confidence`; `added` → `None`) so staff can undo. Students never reach it.
- **`download_url` gate** — a student may download M **iff** in M's effective set. Truth table (unit-tested): plain/
  confirmed/added → **allow**; rejected (incl. added-then-rejected) / never-present → **`NotFoundError` 404** (never
  leaks that the photo exists). Still **no SQL join to `matches`** — contract-safe.

### 4. Writes + the review lane — a new `ReviewService`
Owns the write use-cases + the triage read (services depend only on ports; the shared *pure* helper import is the only
service→service coupling):
- `set_verdict(confirmed|rejected)` — staff on a real match; stamps `resolves_review` if it was `needs_review`.
- `add_missed(student_id)` — report-a-miss; **if already an ML match → store `confirmed`** (keeps "an `added` row implies
  no raw match" clean); else `added`.
- `self_reject(media_id)` — student "this isn't me"; **verifies current effective membership first** (else 404 — never
  leaks a photo they can't see); upserts `rejected` (overrides a staff `added`); `corrected_by` = the student's user id.
- `delete_correction` — undo → reverts to raw ML truth (the only undo for an `added`; staff-only).
- `event_review(event_id)` — unresolved `needs_review` matches grouped by media, for the lane.

### 5. Counts — dashboard effective, BP2 lists deliberately raw
The BP1 dashboard "N to review" becomes **unresolved** = `count_needs_review(raw) − count_resolved()` (both single
indexed counts, subtracted in `DashboardService`, clamped ≥ 0 — both per-`(media,student)`, so they balance 1:1 and
re-inference churn can't drive it negative). **Documented divergence:** the **BP2 list rollups** (`ListingService`) stay
**raw ML** for v1 (galleries = the effective source of truth; overlaying those batch rollups is a deferred follow-up) —
noted in `listing_service.py`.

### 6. Notifications respect the overlay (revises BP4/decisions/0041)
`NotificationService` gains the correction-repo dep and applies the overlay so a rejected student is **never** a notify
target or roster entry, and a report-a-miss `added` student **is** — closing the gap where "reject hides it from the
student" was undercut by a still-firing "new photos" ping. Both the staff targets/roster (`_matched_students` →
`effective_event_pairs`) and the student's own derived signal (`student_notifications` → `effective_student_pairs`) are
overlaid.

### 7. Routes, permissions, frontend
- New `Permission.MATCH_REVIEW` (admin + teacher). Staff `review.py`: `POST /v1/media/{id}/appearances/{student_id}`
  {verdict}, `POST /v1/media/{id}/appearances` {student_id} (report-a-miss), `DELETE /v1/media/{id}/appearances/{student_id}`
  (undo), `GET /v1/events/{id}/review`. Student on `me.py`: `POST /v1/me/media/{id}/not-me` (via `StudentSelfScope`, no
  student_id in the body). `MediaAppearanceResponse` gains `verdict` + nullable `confidence`.
- FE: the **staff photo detail** (`/photos/[mediaId]`) becomes the review surface — per-appearance verdict badge +
  Confirm / Not-this-person / Undo, a report-a-miss "Add a student" picker (roster minus present); the **event gallery**
  gains a **"Needs review (N)"** tab; the **student `/me` lightbox** gets **"This isn't me"** → the photo drops.
- FE (post-review refinements): (a) staff were reaching the correction controls **only** via the needs-review lane → the
  editor was extracted into a shared **`AppearanceEditor`** (used by the photo detail *and* the gallery **lightbox**),
  and the staff gallery grids (event All / By-student + the student-detail "appears in") pass **`canManageAppearances`**
  so staff can confirm/reject/undo + add-a-missed-student **inline on any photo, needs-review or not**. Students'
  `/me` grid leaves it off (default) — they still only get "This isn't me". Server-gated by `match:review` regardless.
  (b) the editor UX was tightened after live feedback: each student is **one compact row — name + confidence + an
  inline X** to remove (reject an ML match / undo a staff add), rejected students hidden (re-addable via the dropdown);
  report-a-miss is a **dismissible "Add students" dropdown** (Radix **Popover** — new dep `@radix-ui/react-popover`;
  portals so it never clips inside the lightbox) with a **searchable multi-select** (tick any number → "Add (N)", fired
  concurrently with partial-failure handling), always present (reads "Everyone's already in this photo" when the roster
  is exhausted). Confirm/Undo buttons were dropped as clutter — remove-then-re-add round-trips through the same two
  affordances.

## Verification

- BE gate green: ruff + mypy + layering + **430 passed, 27 skipped**. New: `test_review_service.py`,
  `test_review_routes.py`, `test_me_not_me_routes.py`, BP5 overlay/download-truth-table + all-six-reads tests in
  `test_gallery_service.py`, the dashboard subtraction/clamp test, the notification-overlay tests, and **gated
  real-Postgres** `test_match_corrections_upsert_get_delete_list_and_scope`. **Migration `0006` applied + reversed
  cleanly on a throwaway Postgres** (never the dev DB).
- FE gate green: `eslint` + `tsc --noEmit` + `next build`.
- **2× review→fix loop:** R1 (correctness / **the entitlement gate** / overlay / SQL / tenant / hooks / migration) —
  **no bugs, no gate bypass**: every download/self-reject/rejected-hides case traced correct and tested; tenant holds
  (real adapter filters `school_id`, tenant-scoped `_require_*` run first); one cosmetic NIT fixed (a missing "Rejected"
  pill in `AppearanceList`). R2 (edge / quality / coverage / a11y / copy) — fixed: two missing overlay tests
  (`event_student_media`, `student_events`), the dashboard-subtraction test, the `listing_service` raw-vs-effective doc
  note, a `make_match_correction` fixture footgun comment; and **F8** (notifications used raw appearances) fixed with
  owner sign-off (decision 6 above).

## Tooling fix (found on bring-up)

`0006` failed to auto-apply on the running stack (runtime `UndefinedTable` on `match_corrections`). Root cause: a
pre-existing bug in `scripts/up.ps1` — its migration step ran only the ML `migrate` service, never the backend's
separate `backend-migrate` one-shot (own chain / `alembic_version_backend`), and step 3 starts the apps with `--no-deps`
so Compose's `backend → backend-migrate` dependency edge was skipped too. So the **backend chain was never applied via
`up.ps1`** (earlier `0001`–`0005` had been applied by a full `docker compose up` or by hand). Fixed: `up.ps1` now runs
**both** one-shot chains (`migrate` **and** `backend-migrate`) before the apps. `0006` was applied to the running `app`
DB via `docker compose run --rm backend-migrate` (non-destructive; verified `0005 → 0006`).

## Follow-ups

Deferred (documented): reconciling the **BP2 list rollups** to effective counts; a per-face **report-a-miss on a
specific frame**; surfacing the **`reason`** field in the UI. **Next: BP6** (per `product/03`).
