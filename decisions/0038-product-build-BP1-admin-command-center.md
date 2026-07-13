# 0038 — Product analysis + Build BP1: Admin Command Center

**Date:** 2026-07-13
**Status:** Accepted

## Context

The system is v1 feature-complete + hardened (ML + BE + FE, decisions 0008–0037), but the owner's read was "functional,
not a product." A **whole-product analysis** was run and its durable outputs live under a new top-level **`product/`**
folder (so future sessions don't re-explore): `00-knowledge-base.md` (what exists, all 3 services), `01-product-skills-and-rubric.md`
(the D/P/X lenses + per-persona bar + T1–T8 targets), and `03-improvement-roadmap.md` (the phased **BP1–BP8** build
roadmap; a separate scored `02-product-review.md` was folded into the roadmap's rationale). Prioritization was
owner-delegated to the product specialist; **consent/legal is out of scope** (handled by legal via school contracts).

The roadmap's insight: most experience gaps are **display gaps, not data deficits** — the data already flows, so they
need no migration and no ML change. So the build leads with cheap, high-visibility surfacing. **BP1 (this entry)** is
the first slice: turn the one true placeholder (`/dashboard`) into a real command center.

## Decisions (BP1)

### 1. `GET /v1/dashboard` — a school command center, read-only, no migration, no ML change
A new endpoint returns one school's rollup: students by enrollment status, an events lifecycle/in-flight rollup, a
photo total/pending, and three **needs-attention** signals (events with photos not distributed · enrollment failures ·
matches needing review). Every number is a **grouped/EXISTS/filtered query** over the backend's own rows (and the ML
`matches` seam it already reads) — constant queries per request, no N+1, no stored aggregate.

### 2. Aggregates live as new methods on existing ports (hexagonal layering preserved)
`StudentRepository.enrollment_counts`, `EventRepository.status_counts` (→ new frozen `EventRollup`) +
`count_not_started_with_media`, `MediaRepository.school_status_counts`, and `MlResultsReader.count_needs_review` — the
last a filtered count touching **only the already-declared `matches` columns** (`school_id`, `needs_review`), so the
Phase-7 `information_schema` contract test is unaffected and `db/ml_read.py` is untouched. A pure `DashboardService`
(ports-only, mirrors `GalleryService`) composes them; SQL stays in adapters (layering grep + `test_layering.py` green).

### 3. New `dashboard:view` permission (code, not migration)
Added to the `Permission` enum + `ROLE_PERMISSIONS` for `school_admin` + `teacher`. Chosen over reusing an
action-scoped perm because the dashboard is a cross-cutting read that should grant/revoke independently. Tenant
`school_id` is always from the token (`tenant_of`), never the URL; `platform_admin`/`student` get 403.

### 4. "Undistributed" alert counts only **active** events
`count_not_started_with_media` filters `status = active` as well as `processing_status = not_started` + has-media: an
archived event can't be Processed (the route 400s), so surfacing one as "ready to distribute" would point staff at an
un-actionable event. (Caught in the round-2 review — the one real-behavior fix.)

### 5. Frontend — real dashboard + nav information-scent, reusing the existing kit
`app/(school)/dashboard/page.tsx` becomes a command center: the school name, a `StatCard` row (tabular numerals —
Students enrolled/pending/**failed**, Events, Photos), a needs-attention alert list (only the non-zero signals, each
linking to the relevant list), quick actions, and a **first-run invitation** for a fresh school (not a placeholder).
A `useDashboard(enabled)` hook (SWR key `"dashboard"`) is shared by the page and the **nav badges** in `app-shell.tsx`
(Students · N failed / Events · N to distribute) so it's one request; `enabled=false` (key → null) suppresses the
fetch for `platform_admin`/`student` (who'd 403). New `StatCard` primitive; no new dep, existing `@theme` tokens.

## Verification

- BE gate green: ruff + mypy + layering grep clean; **245 passed, 15 skipped** (`uv run pytest services/backend`).
  New tests: `test_dashboard_service.py` + `test_dashboard_routes.py` (RBAC + tenant-from-token + the archived-event
  exclusion), and **gated** real-Postgres coverage of every new aggregate query's SQL + tenant scoping
  (`adapters/test_postgres_repos.py`, `adapters/test_ml_read.py` — run in CI's integration job / with `BE_TEST_DATABASE_URL`).
- FE gate green: `eslint` + `tsc --noEmit` + `next build` (Node ≥ 20.9).
- **2× review→fix loop** run: round 1 (correctness/async/error-handling) found no bugs; round 2 (edge cases/quality/
  coverage) added the gated adapter-SQL tests and the active-only alert fix. No migration, no ML change.

## Follow-ups (roadmap `product/03`)

BP2 (list richness + search/filter/sort, reusing these aggregates) is next; then BP3 (student receive experience),
BP4 (distribution — the flagship), BP5 (trust/accuracy loop), BP6 (video), BP7 (onboarding/bulk), BP8 (ops).
