# 0059 — Product Build BP11b: Event term/category + month calendar

**Date:** 2026-07-26
**Status:** Accepted

## Context

BP11 (organizing structure) is being built in three approve-before-commit slices. **BP11a
(student classes) landed** ([0058](0058-product-build-BP11a-student-classes.md)). **BP11b** is the
events half: an event was just a name + optional date + status, and the events screen was one flat
chronological list — no way to label events by **term** or **category**, and no **calendar** to see
them by date. At Greenfield scale (~120 events/year) that's the findability half of the review's
theme B ([`02`](../product/02-product-review.md) §3.2⑤/§3.3①, lenses P3/P5).

Per the owner-approved plan (an HTML explainer + a decisions Q&A, 2026-07-26): **categories are
per-school configurable** (not a hardcoded enum — an owner change during the HTML review), a
free-text **term**, and a **read-only month calendar**. The **event↔class link is deferred to
BP11c** (teacher delegation); cohort-scoped *matching* stays **BP15**. No ML change.

## Decision (BP11b)

### Backend — configurable categories + term + calendar filters (migration `0014`)

- **`event_categories`** — a tenant-owned category (id, `school_id`→schools CASCADE, name,
  timestamps; `UNIQUE(school_id, name)`), mirroring BP11a's `student_groups`. **Seeded with 6
  defaults** (`Sports · Academic · Arts · Trip · Ceremony · Other`) **on school-create**
  (`OnboardingService.create_school` → `EventCategoryRepository.seed_defaults`, injected) **AND**
  into every **existing** school in migration `0014`'s data step (`INSERT … SELECT` over `schools`
  CROSS JOIN the 6 names, `gen_random_uuid()`). `seed_defaults` is idempotent (case-insensitive
  skip).
- **`events.category_id`** — nullable FK → `event_categories`, **ON DELETE SET NULL** (removing a
  category un-tags its events, never deletes them). **`events.term`** — nullable free text. Index
  `ix_events_school_category (school_id, category_id, event_date, id)`.
- **`EventCategory` VO** + `DEFAULT_EVENT_CATEGORIES` in `domain/models.py`; `Event` gains
  `term`/`category_id`/`category_name` (the name **denormalized** via a LEFT JOIN on the object
  reads, like `student_group_name`). A pure **`EventCategoryService`** (list / add [strip +
  case-insensitive dedupe → **409**] / remove [→ 404 if foreign] / seed).
- **`EventRepository`**: `create`/`update` thread `category_id`/`term`; `_filtered` gains
  `category_id` (malformed → `false()`, never `IS NULL`) / `term` (exact) / `date_from`/`date_to`
  (`event_date >=/<=`, a null date excluded — what the calendar wants), threaded through
  `list_page`/`count_page`/`list_ids` (both the row-native and count-sort id-scan paths, exactly the
  BP11a pattern); `list_terms` (distinct non-null terms). `EventService.create_event`/`update_event`
  validate the category is in-school (**404**), `_clean_term` (strip/empty→None/cap 100); term/
  category follow the event-update **`None` = leave unchanged** convention — **term/category can't be
  cleared** via PATCH (consistent with description/date, [0027](0027-events-media-enqueue-status.md)).
- Routes: `GET/POST /v1/event-categories`, `DELETE /v1/event-categories/{id}` (all **`event:manage`**
  — admins + staff, **no new permission**); `GET /v1/events` gains `category_id`/`term`/`date_from`/
  `date_to`; `GET /v1/events/terms` (registered **before** `/{event_id}` so the literal wins).

### Frontend — filters + labels + the calendar

- **`lib/events/calendar.ts`** (pure, the correctness-critical module): **timezone-safe**
  `parseLocalDate` (parse `YYYY-MM-DD` into a *local* Date — never `new Date(iso)`, which is
  UTC-midnight → off-by-one west of UTC) + `toISODate` (never `toISOString`) + `buildMonthGrid`
  (fixed 6×7 grid, `inMonth`/`isToday`, `gridStart`/`gridEnd`) + `shiftMonth`/`currentMonth`/
  `monthLabel`.
- **`lib/events/categories.ts`**: `categoryColor(id)` — a deterministic hash into a fixed pale-tint
  palette (the red/error tint deliberately excluded) so any category (default or custom) gets a
  stable color for the calendar pill + list/detail badge (no stored color; two customs may collide —
  visual only).
- **`components/events/month-calendar.tsx`**: a controlled, read-only month grid — the parent builds
  the grid **once** and passes it down (so the fetch window == the rendered cells). `role="grid"`/
  `row`/`columnheader`/`gridcell` with a per-cell `aria-label` (readable date + event count),
  `aria-current="date"`, an `sr-only role="status"` month-count; category-colored `<Link>` pills
  capped at 3 + "+N more"; undated events dropped with a note.
  **`components/events/manage-categories-dialog.tsx`**: list / add / **confirm-then-remove** (a
  `ConfirmDialog`, since delete un-tags events).
- **`app/(school)/events/page.tsx`**: a **List ⇄ Calendar** `Tabs` (existing primitive); shared
  **category** + **term** native `<select>` filters (from `useEventCategories`/`useEventTerms`, with
  the BP11a "derived, not effect-reconciled" stale-filter guard); a **Category** badge column; a
  **Manage categories** button; the create/edit dialogs gain a category `<select>` (default "Other"
  when present) + a term `<Input>`. The **`CalendarView`** mounts only when the tab is active (Radix
  unmounts inactive content) → `useMonthEvents` (one bounded fetch over the grid window, `limit 200`;
  a `total > shown` truncation note). The edit dialog omits "No category" once an event is
  categorized (clearing unsupported).

## Why

- **Categories as tenant rows, not an enum** (the owner's change). A fixed enum can't grow per
  school; a tenant `event_categories` table (the BP11a `student_groups` pattern) lets admins + staff
  add "Chess Club" etc., seeded with sensible defaults so it works out of the box.
- **Seed on both paths.** New schools seed in the create flow; existing schools seed in the
  migration — so every school, old and new, starts with the 6.
- **`event:manage`, not a new permission.** The owner asked for "admins and staff" — exactly who
  holds `event:manage`. (Contrast BP11a's `class:manage`, admin-only.)
- **The timezone trap is the one real risk**, contained in one pure module. `new Date("2026-07-04")`
  is UTC-midnight → the wrong day west of UTC; all calendar math parses parts into a local date and
  never round-trips through `toISOString`.
- **Reuse the BP9 list machinery + BP11a patterns** — one WHERE clause per filter, the LEFT-JOIN
  denorm, the derived stale-filter guard, the SET-NULL un-tag.

## Security

- **Tenant isolation by construction.** Every category row + read/write is `school_id`-scoped from
  the token; a non-null `category_id` on create/update is validated in-school (**404**, never a
  cross-tenant tag); the list filters AND under the school scope. No cross-seam ML join.
- **`event:manage`** gates category CRUD (a student → 403); a teacher can add **and** delete
  (intended — staff manage events + their categories).
- **404 not 403** for a foreign category; a duplicate name → **409** (+ the DB `UNIQUE` as the second
  line).

## Alternatives considered

- **A fixed category enum + CHECK** (the first HTML draft). Rejected on owner review — a school can't
  add its own; a per-school table is the same BP11a pattern with a small data-migration seed.
- **A stored `color` column + a picker.** Rejected for v1 — a deterministic hash gives every category
  a stable color with no extra UI/column; a picker is a future refinement.
- **A date library (date-fns/dayjs) for the calendar.** Rejected — the month grid is ~40 lines of
  pure `Date` math with no new dependency; the only subtlety (the TZ parse) is handled explicitly.
- **Category rename / inline "+ Add" in the event form.** Deferred — list/add/remove via the Manage
  panel covers v1; rename = remove + re-add.
- **A day drill-in / clickable "+N more" on the calendar.** Deferred (read-only v1); the gridcell's
  `aria-label` still surfaces the full count to screen readers.

## Consequences

- **No ML change, no new backend dependency, no new env var, no new permission.** One migration
  (`0014`, + a seed).
- **Honest limits (documented):** term is free text (a picker from `list_terms` mitigates drift; no
  normalize) and **can't be cleared** via PATCH (nor can category — consistent with description/date);
  category rename is deferred (remove + re-add); a custom category's color is auto-assigned (collisions
  possible — visual only); the calendar is **read-only month-only** (no week/agenda, no drag), undated
  events live only in the List tab, and a month view fetches ≤200 events (a "switch to list" note
  beyond); `role="grid"` without arrow-key roving (pills tab-reachable, mirroring the BP10 picker
  trade-off); the events **list rollups stay raw ML** (BP2 divergence, unchanged). BP11c (teacher
  delegation) is the last slice.
- **Verification:** BE ruff + mypy + **510 passed / 34 skipped** + layering; `test_bp11b_calendar.py`
  (26: category lifecycle add-409/delete-untag/foreign-404/seed-on-create; event create/update with
  category+term + foreign-404 + term-clean/can't-clear; the category/term/date-range filters incl. the
  count-sort path + open-ended range + the route PATCH; blank/over-length category name; teacher
  add+delete; `/events/terms`; auth) + a **gated real-Postgres** round-trip
  (`test_event_category_crud_seed_join_filters_and_cascade`: CRUD + seed + LEFT-JOIN name + all
  filters + **SET NULL cascade** on a throwaway `bp11b_test`, dropped; dev `app` untouched);
  migration `0014` verified up→down→up **+ the seed** on a throwaway `bp11b_migtest` (dropped). FE
  tsc + lint + `next build` green. 2× review loop (**R1 SHIP — 0 blockers**: the timezone module,
  tenant isolation, the seed, the LEFT-JOIN/filter/count-sort paths, SET NULL, route ordering,
  can't-clear, async all verified; **R2** → confirm-before-category-delete, a month-truncation note,
  calendar gridcell aria-labels, grid-built-once, the edit can't-clear UX, dropped the red tint, +4
  tests). No commit/push without an explicit request.
