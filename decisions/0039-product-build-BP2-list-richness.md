# 0039 — Product Build BP2: List data-richness & scale

**Date:** 2026-07-14
**Status:** Accepted

## Context

Second phase of the product-improvement build track (roadmap `product/03`, after BP1 [decisions/0038]).
The four admin lists (schools/staff/students/events) were real but **count-free** with **no search/filter/sort** —
failing the rubric's efficiency-at-scale lenses (P5/P8) and target T5. Every count needed already exists in the DB
(or the ML `matches` seam the backend already reads), so this is **query-only: no migration, no ML change**.

## Decisions (BP2)

### 1. Per-row counts through a new `ListingService` — existing services untouched
Rather than thread the ML `matches` reader into `EventService`/`StudentService`/`OnboardingService` (and churn their
constructors + tests), a new **`services/listing_service.py`** owns the enriched-list reads (same composition style as
`GalleryService`/`DashboardService`). It has the 6 read ports it needs and **zips per-row counts to rows in-Python —
no N+1**. The GET list routes now call `container.listing_service()`; the write services keep their single-item paths.

### 2. New batched aggregate methods on existing ports (query-only)
- `MlResultsReader.event_match_counts` (per event: `COUNT(DISTINCT student_id)` + `COUNT() FILTER(needs_review)`) and
  `student_appearance_counts` (per student: appearances + distinct events) — grouped scans over the **already-declared**
  `matches` columns (contract test unaffected).
- `MediaRepository.counts_by_event` (photos per event, tenant-scoped).
- Platform rollups (cross-tenant, only reachable behind `school:manage`): `UserRepository.role_counts_by_school`
  (excludes null-school platform admins), `StudentRepository.counts_by_school`, `EventRepository.counts_by_school`.
- New pure value objects: `EventMatchCounts`, `StudentAppearanceCounts`, `SchoolRollup`.

### 3. List-variant response schemas (write DTOs stay frozen)
`EventListItem(EventResponse)` + `StudentListItem(StudentResponse)` add flat counts; `SchoolWithRollupResponse(SchoolResponse)`
nests a `rollup`. The single-item GET/POST/PATCH keep the leaner base models. Built via `cls(**base.model_dump(), …)`.

### 4. New endpoint + one additive field
- **`GET /v1/schools/{id}/admins`** — the school administrator roster (the F2 detail page was add-only for lack of a
  list endpoint; now it lists + revalidates after add). Platform-only (`school:manage`).
- **`UserResponse.created_at`** — additive (staff "added" date + roster; harmless on `/me`). Every construction goes
  through `from_user`, so nothing breaks.

### 5. Frontend — counts, search, filter, sort across all four lists
- Enriched hooks/types (`EventListItem`/`StudentListItem`/`SchoolWithRollup`, `useSchoolAdmins`).
- Two shared bits: **`SearchInput`** (client search) and **`useSort`** + **`SortableHead`** (client sort with a
  direction-aware comparator so `Array.sort` stability holds in both directions). Reused the F5 **`FilterChips`**
  radiogroup for the enrollment (students) and status (events) filters, with live per-bucket counts.
- Students: appearance/event counts + enrollment filter + search + sort. Events: photos/matched/**needs-review** pill +
  active/archived filter + search + sort. Schools: admins/teachers-of-max/students/events rollup columns + search + sort
  (+ the detail page gains `StatCard` rollups + the admin roster). Staff: added-date column + search + sort.

## Verification

- BE gate green: ruff + mypy + layering clean; **258 passed, 17 skipped** (`uv run pytest services/backend`). New:
  `test_listing_service.py` (zip joins, zero-fill, ghost-key drop, rollups, roster), `test_listing_routes.py` (counts +
  rollups + roster + platform-only RBAC), and **gated** real-Postgres coverage of all six aggregates' SQL + tenant
  scoping (`adapters/test_postgres_repos.py`, `adapters/test_ml_read.py`).
- FE gate green: `eslint` + `tsc --noEmit` + `next build` (Node ≥ 20.9).
- **2× review→fix loop:** round 1 (correctness/SQL/tenant) — no bugs; round 2 (edge/quality/coverage) — fixed a
  `useSort` tie-stability bug on the default events view (sort-then-reverse → direction-aware compare), added the
  ghost-key drop test, a `SearchInput` icon `aria-hidden`, and a cleaner keyed roster revalidation.

## Follow-ups (roadmap `product/03`)

Deferred (documented): the students-list **reference thumbnail** (needs a new signed-URL endpoint for reference photos
+ lazy loading like the gallery — a mini-feature), CSV bulk import, and staff edit/disable/resend (BP7). Next up: **BP3**
(student receive experience — Pinterest-grade gallery, FE-only).
