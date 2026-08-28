# 0078 — Product Build BP23: Run it on numbers (instrumentation)

- **Date:** 2026-08-28
- **Status:** implemented (gate green; 2× review loop clean)
- **Phase:** **BP23 (Run it on numbers)** — Round-3 review theme **O**
  ([0064](0064-product-review-round-3-ux.md), [`product/06`](../product/06-product-review-round-3-ux.md) §O,
  roadmap [`product/07`](../product/07-improvement-roadmap-round-3.md) BP23), redeeming R3-S6-01..11.
  **One phase, all four owner-chosen groups. Backend + FE. One migration (`0019`, `media.uploaded_by`);
  no ML change, no new permission, no new dependency.**

## Context

Theme O — "the owner runs blind." The product collected the data to answer its own hardest questions and
read almost none of it. Three Highs plus a cluster of Mediums:

- **"Delivery rate" measured the button, not the audience (R3-S6-03).** It was announced ÷ events; per-event
  opens (`notification_reads`) existed and were never aggregated — a school could read 100% "announced" with
  almost no rosters ever opened, and nothing contradicted it.
- **The accuracy ground truth was collected and never read (R3-S6-06).** Every confirm/reject/"not me" lands
  in `match_corrections` with a verdict + timestamp; the only aggregate subtracted from the review backlog.
  "Is matching getting better or worse?" — the churn driver — was unanswerable.
- **Teacher attribution was a closing window (R3-S6-04).** Pricing rides on `max_teachers`, yet per-teacher
  last-login was stamped-but-unexposed, `events.created_by` stored-but-hidden, and **media had no uploader
  column at all** — unrecoverable retroactively.

Two Explore passes + a Plan-agent design review confirmed: **only slice 1 needs a migration**; everything else
is query-only new aggregates over the backend's own tables, composed in the BP14 `AnalyticsService`.

## Decision

Four groups, one phase.

### A. Attribution + the migration (R3-S6-04)
- **`media.uploaded_by` — migration `0019`** (nullable UUID FK → `users`, **ON DELETE SET NULL**, no index,
  no backfill). The real work is a **plumb** (`register_media` had no actor param): `uploaded_by` threaded
  route (`actor.id`) → `MediaService.register_media` → `MediaRepository.create` → the domain `Media` VO, all
  additive.
- **`last_login_at` exposed** (already populated at login since 0016): `domain.User` + `postgres_users._to_user`
  + `UserResponse.from_user` (defaulted kwarg) + a new **row-native** `UserSort.LAST_LOGIN_AT` (nulls last on
  ASC) → a **"Last sign-in"** staff column + sort.
- **Event creator** resolved **in-Python** via `UserRepository.get(created_by)` in a new
  `EventService.get_event_detail` (`EventDetail` VO) — **not** a JOIN on the shared `postgres_events` select
  (which feeds every list/get path) → additive `EventResponse.created_by_email` on the **detail route only**
  (list rows leave it null).

### B. Instrument the flagship claims (R3-S6-02/03/06/07)
- **Event reach — the R1 correction from the plan:** the true "opens ÷ roster" is **not seam-free** (the
  per-event roster comes from the ML `matches` seam + BP5 overlay — an in-Python composition would be an **N+1
  over the seam**, which the analytics module forbids). Ships **"Event reach" = (announced ∩ opened) ÷ events
  announced** — `NotificationReadRepository.distinct_opened_event_ids` (one seam-free DISTINCT scan)
  **intersected in-Python** with the currently-announced event ids (R2 fix — an honest floor that never
  over-reports an event opened then un-announced).
- **Saved:** `DownloadAuditRepository.count_distinct_saver_students` = `count(DISTINCT subject_student_id) …
  WHERE subject_student_id IS NOT NULL` (non-null only on a student self-save → staff bulk-downloads excluded).
- **Engagement that can decline:** `monthly_first_open_counts` over `notification_reads.created_at` (the
  **immutable** first-ever open, distinct from reset-on-reannounce `seen_at`) → a first-opens `TrendChart`.
- **Accuracy visible:** `MatchCorrectionRepository.monthly_verdict_counts` (month × verdict) → a **"Quality"**
  section: **confirm rate** = `confirmed ÷ (confirmed + rejected)` + a separate **wrong-person rate**;
  **`added` is EXCLUDED from the precision denominator** (report-a-miss = a recall signal) and shown on its own.
  Descriptive only — the matching *model* work stays parked BP15.

`AnalyticsService` gained `corrections` + `audit` ports; `SchoolAnalytics` gained `students_saved`,
`events_opened`, `MonthPoint.first_opens`, and `quality: tuple[QualityPoint, ...]`.

### C. Answers behind the numbers (R3-S6-08/09 + S5-10/A2-03/S1-08/11)
- **Never-signed-in / never-opened filters:** `never_signed_in` (`users.last_login_at IS NULL` — the students
  select already INNER JOINs `users`) + `never_opened` (`NOT EXISTS (SELECT 1 FROM notification_reads …)` — a
  **same-schema anti-join, NOT the ML seam**), threaded through `postgres_students._filtered` →
  `list_page`/`count_page`/`list_ids` → `ListingService` → the route (`ActivityFilter` enum query params
  `login`/`opened`, 422-safe). FE: one "activity" `<select>` drives both (setting one clears the other), and the
  dashboard **enrollment-failures** alert deep-links to `/students?status=failed`.
- **Per-child engagement — the R2 correction from the plan:** a **separate `GET /v1/students/{id}/engagement`**
  (`EngagementService`, `student:manage`) — **not** fields on the write-path `StudentResponse`. Composes
  events/photos-appearing (reader + BP5 overlay, in-Python) + events-opened/last-opened (`reads.list_for_student`)
  + downloads (`download_audit.count_recent(student_id=…)`) → the student-detail **Engagement card**.
- **Roster answers:** `RosterEntry` gains `first_seen_at` (`notification_reads.created_at` via
  `first_seen_for_event` — the persistent ever-opened) + `download_count` (per-(student,event)
  `download_counts_by_student_for_event`); `NotificationService` gained an `audit` port → two roster columns.

### D. Estate activation view (R3-S6-01/10 + A1-03/05)
- `SchoolFunnel` gains **`created_at`** (free), **`not_started`** (`events == 0`), **`days_to_first_delivery`**
  (`first_distributed_at_by_school()` = `min(coalesce(notified_at, completed_at))` under the announced predicate
  − `school.created_at`, clamped ≥ 0), and **`stalled_since`** — the R2 correction: no clean timestamp exists, so
  anchor it on `last_event_created_at_by_school()` = `max(events.created_at)` ("no event since …"; None if never),
  **not** `school.updated_at`. Two new grouped estate scans.
- The estate funnel **sorts client-side** (the list is fully materialized/unpaginated — no backend sort param).

## Consequences / honest limits (documented)

- **Audience-weighted open rate** (Σ seen ÷ Σ roster per event) needs a **roster-snapshot write at announce
  time** (or an N+1 over the ML seam) — both scoped out; BP23 ships **event reach** ("events with ≥1 opener").
  Reach's numerator is the **in-Python intersection of the currently-announced event ids with the opened
  event ids** (R2 fix — supersedes the earlier count+clamp), so it's a true floor bounded by
  `events_distributed` and can never over- or mis-report an event opened then un-announced.
- **Storage-bytes / per-school cost tracking** (R3-S6-05 tail) needs upload-path changes — a future slice.
- **Trends stay query-derived from timestamps** (no snapshot table) — "enrolled over time" is a current funnel,
  not a historical line.
- The accuracy **model** work stays parked **BP15** — BP23 ships the *metric* only.
- `stalled_since` = "no event since `max(events.created_at)`" — an honest anchor, not a true inactivity clock.
- The roster `seen` still **resets on re-announce**; `first_seen_at` is the persistent ever-opened beside it.
- `events_opened`/`students_saved` share the BP14 total-student denominator convention (a documented coarseness
  — a non-enrolled student can't act, so the rate is a floor).
- **No migration beyond `0019`, no ML change, no new permission, no new dependency.**

## Verification

- **Backend:** ruff + mypy + layering clean; **604 passed / 46 skipped** (+ `test_bp23_instrumentation.py`:
  register-stamps-uploaded_by / created-by-email-resolve-or-None / reach-intersects-announced∩opened /
  reach+savers+quality composition / first-open-trend-can-decline / empty-school-reads-zero /
  never-signed-in+never-opened filters / engagement-composition+404 / roster-first-seen+download-count /
  roster-seen-resets-but-first-seen-persists / estate-age-axis; + the route smoke: created-by-email,
  engagement perms+404, activity-filter 422).
- **Gated real-Postgres** (7 new round-trips on a **throwaway** `bp23_test`, dropped; dev `app` untouched):
  `media.uploaded_by` round-trip + **SET NULL on uploader delete**, `last_login_at` map + sort, reach/first-open/
  first-seen, distinct-savers (staff excluded) + per-event download counts, monthly verdicts, estate
  first-distributed/last-event, and the student activity filters — each **tenant-scoped**.
- **Migration `0019` verified up→down→up** on a throwaway `bp23_migtest` (dropped; dev `app` untouched — column
  + FK appear, drop, re-appear).
- **Frontend:** tsc + lint + `next build` green (the students/staff/estate/dashboard/events lists stay `○`
  static via their Suspense boundaries).
- **2× review loop:** **R1 (correctness/tenant/cross-seam/async) — SHIP, 0 blockers**: all 8 new aggregates
  tenant-scoped, no ML-seam SQL join anywhere, the migration + register plumb + read-model additivity + async
  all verified → 1 should-fix (Open-rate could read >100% if an event was opened then un-announced). **R2
  (numbers-honest/a11y/copy/edges) — 0 blockers**: 2 should-fix (the estate `SortHead` lacked `aria-sort`;
  the engagement card's "Events"/"Photos" labels were ambiguous) + 4 nits. **Fixes applied:** the >100% edge
  was first clamped (R1) then **superseded by the honest announced∩opened intersection** (R2) — reach can
  never over-report; added `aria-sort` to the estate sort headers; renamed the engagement labels to "Events
  they're in"/"Photos they're in"; gated the confirm/reject rate cards + intro on `adjudicated > 0` (so a
  report-a-miss-only school shows no empty `—` cards); made the staff `last_login_at` sort `nulls_last()` in
  both directions (never-signed-in always sits last, not surprisingly-first on DESC); and added the
  reach-intersection + roster seen-resets-but-first-seen-persists tests. Gate re-verified green after each.

## Next

The recommended Round-3 tail continues **BP24** (two-way doors) — plus the still-open **BP22 slice 4** (student
"This isn't me" safety) whenever the owner re-opens it. A phase starts only on owner pick + scope re-confirm.
