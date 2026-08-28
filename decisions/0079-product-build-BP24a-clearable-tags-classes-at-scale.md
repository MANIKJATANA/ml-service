# 0079 — Product Build BP24a: Two-way doors (clearable tags + classes at CSV scale)

- **Date:** 2026-08-28
- **Status:** implemented (gate green; 2× review loop clean)
- **Phase:** **BP24a** — the backend half of **BP24 (Two-way doors)**, Round-3 review theme **P**
  ([0064](0064-product-review-round-3-ux.md), [`product/06`](../product/06-product-review-round-3-ux.md) §P,
  roadmap [`product/07`](../product/07-improvement-roadmap-round-3.md) BP24), redeeming R3-A2-05/06 + the
  aggravator L18. **Owner: two sub-phases** — this is the backend-touching one (slices 1 + 3); the FE
  error-survival sweep (slices 2/4/5) is **BP24b**. **No migration, no ML change, no new permission, no new
  dependency.**

## Context

Theme P — "mistakes become recoverable." Two backend one-way doors:
- **Event tags could be set but never cleared (R3-A2-05).** The 0027 "None = unchanged" PATCH convention omitted
  the empty option, so a mis-tagged category/term/**class** (a wrong class mis-scopes teacher focus lists
  *forever*) had no undo but recreate-and-reupload — and create-event **silently preselected "Other"**, so
  default-accepted events were permanently categorized (L18).
- **Class assignment didn't scale (R3-A2-06).** Putting ~800 imported students into ~25 classes was ~800
  search-and-clicks; the CSV import carried no class column and there was no paste path.

## Decision

### Slice 1 · Clearable event tags — **a documented revision of the locked 0027 convention** (owner-approved)
The three **tag** fields (`category_id`/`term`/`student_group_id`) become **tri-state** on the event PATCH; the
rest (name/description/event_date/status/auto_notify) keep 0027's "None = unchanged" (nothing asks to clear them):
- A tiny **`UnsetType`/`UNSET`** enum sentinel (`domain/models.py`) — an `Enum` singleton so mypy narrows
  `is UNSET` / `isinstance(x, UnsetType)` cleanly — distinct from `None`.
- The route (`api/routers/events.py::update_event`) reads Pydantic v2 **`body.model_fields_set`** (no
  `exclude_unset` precedent existed — this introduces the pattern, scoped to one route) and passes
  `body.field if "field" in provided else UNSET` for the three tags: **omitted → UNSET → unchanged**, an explicit
  **`null` → None → cleared**, a **value → set**.
- `EventService.update_event` + `EventRepository.update` (+ port + the fake) type those three params
  `str | None | UnsetType = UNSET`; the repo does `if x is not UNSET: row.x = req_uuid(x) if x else None`.
  `_validate_category`/`_validate_group` validate **only a real id** (`isinstance(str)`), so UNSET + None (clear)
  skip the check and a **foreign id still 404s**.
- **FE:** the edit dialog always offers "No category" / "School-wide" / empty-term and sends `value || null` when a
  tag **changed** (emptied → explicit `null`, unchanged → omitted); `updateEvent`'s patch type is `string | null`.
  Create-event **stops preselecting "Other"** — a new event starts genuinely uncategorized (L18).

### Slice 3 · Classes at CSV scale — **both shapes** (owner call)
**(a) An optional `class` column on the student CSV import** (`lib/csv.ts` header-detects it; absent → today's
name+email, fully back-compatible). `StudentService.bulk_create_students` (rows now `(name, email, class_name?)`)
gained a `groups: StudentGroupRepository` port and **resolves-or-creates the class by name once per distinct name**
(a `class_cache` seeded from the school's existing classes, case-insensitive) then `set_group` — **best-effort**
(a class blip is logged, the student stays `created`; a bad class name never aborts the batch).
**(b) A paste-emails bulk-assign** — `POST /v1/classes/{id}/members/by-email` → `ClassService.
assign_students_by_email` (validates the class → 404 if foreign; trims/dedupes/lowercases; `resolve_by_emails`
[BP10] → `set_group_bulk` [BP11a]) returns `(assigned, unmatched)` so the admin can fix typos. FE: a
`PasteEmailsDialog` on the class detail (a textarea, split on commas/whitespace/newlines).

## Consequences / honest limits (documented)
- **0027 is revised, not repealed:** only the three **tag** fields are clearable; description/event_date keep the
  old "empty = unchanged" (nobody asked to clear them). A BP11b test that asserted the old "empty term = unchanged"
  was updated to the new "explicit-empty clears, omitted leaves".
- **`model_fields_set` is used at exactly one route** — the pattern is introduced deliberately + scoped; it is the
  clean Pydantic-v2 way to tell "omitted" from "explicit null".
- **Class names aren't unique-by-name** (BP11a, no unique constraint) — the CSV auto-create dedupes **within a
  batch**; a rare concurrent second import could create a duplicate-named class (acceptable, documented).
- The paste-emails resolve is bounded by the assign cap (1000, mirrored on the FE as a friendly guard instead of
  a raw 422); an unknown email is reported unmatched, never a cross-tenant probe.
- **No migration** (the tag columns were already nullable; classes already exist), **no ML change, no new
  permission, no new dependency.**

## Verification
- **Backend:** ruff + mypy + layering clean; **617 passed / 47 skipped** (+ `test_bp24_two_way_doors.py`: the
  clear/leave/set × 3-field truth table at the service + a **route round-trip proving `model_fields_set`** (empty
  PATCH leaves, explicit-null clears, value sets, foreign → 404); the CSV class column
  (auto-create/dedupe/assign, back-compat with no column, reuse-existing-by-name, **a class-assign failure keeps
  the student `created`**); the by-email assign (matched/deduped/unmatched, foreign class → 404, **a foreign-school
  email is unmatched — the tenant-leak guard**) + a route shape). **Gated real-Postgres** (throwaway `bp24_test`,
  dropped; dev `app` untouched): the clearable `postgres_events.update` tri-state round-trip.
- **Frontend:** tsc + lint + `next build` green (the events/classes lists stay `○`/`ƒ` as before).
- **2× review loop:** **R1 (correctness/tenant/async/the tri-state truth table) — SHIP, 0 blockers, 0 should-fix**:
  the tri-state contract verified correct in every cell (route `model_fields_set` → service pass-through/validation-
  skip → repo `is not UNSET` clear/set/skip, on both the fake + the gated Postgres repo), the other PATCH fields
  un-regressed, foreign-id still 404, tenant isolation + the batch class-dedupe + all 4 constructor/caller sites
  correct → applied its 1 NIT (hoisted a double `class_name.strip()`). **R2 (edge/back-compat/a11y/copy) — 0
  blockers** → 3 should-fix (a FE 1000-email cap mirror so a huge paste gets a friendly message not a raw 422; the
  foreign-school-email tenant-leak test; the class-assign-failure-keeps-student test) + 2 nits (the unmatched box
  `role="alert"`→`role="status"` since it persists while the toast is transient; "Added 0 students"→"No emails
  matched a student in this school — check for typos") — all applied. Gate re-verified green after each.

## Next

**BP24b** — the FE error-survival sweep: the CSV error loop (preview pre-flag + download-skipped-rows), honest
partial downloads, and the residue (create-teacher roster refresh + the notify-roster collapse/Not-opened filter)
→ `decisions/0080`. Then the recommended Round-3 tail is complete (parked BP12/15/16 + the blocked BP22 slice 4
remain).
