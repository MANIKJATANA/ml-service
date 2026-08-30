# 0085 — Product Build BP28a: Access-log filters + date-range + CSV export

- **Date:** 2026-08-30
- **Status:** implemented (BE + FE gates green; 2× review→fix loop clean). **Committed + pushed.**
- **Phase:** **BP28a** — the first slice of **BP28 (Governance & audit completeness)**, Round-4 findings **R4-A24** (the
  access log had no filter UI though the event/student filters were wired) + **R4-A26** (no CSV export). **BE + FE — no
  migration, no ML change, no new dependency, no new permission, no new env var.**

## Context

The school-admin **Access log** (`/audit`, BP8b) showed a paginated download log but had **no filter UI** — even though
the backend `event_id`/`student_id` filters were wired end-to-end (BP8b/BP23) and merely lacked a front end — and **no
CSV export**. "Who downloaded student X's photos last week?" was page-through-only. 28a surfaces the wired filters, adds
the two genuinely-missing server filters (**date-range** + **actor role**), and a **CSV export**.

**Workflow (owner-directed multi-agent pipeline):** planning agent (full plan, grounded in the BP8b `download_audit`
stack) → plan-review agent (verified the "one real gap" claim — event/student ARE wired, date-range/actor are NOT —
and pinned the two hardenings below) → implementation agent → 2× review loop.

## Decision

### Backend — two genuinely-missing filter params (no migration)
- `DownloadAuditRepository.list_recent`/`count_recent` (port + postgres adapter + fake) gain `created_from`/
  `created_to`/`actor_role` (all default `None`), threaded through `AuditService.school_download_log` to
  `GET /v1/audit/downloads`. **Two hardenings from the review:**
  - **Date params are typed `datetime | None`** and **`actor_role` is typed `Role | None`** at the route, so a
    malformed date or an unknown role **422s at the FastAPI boundary** (before the handler); the route passes
    `actor_role.value` (the string) to the service.
  - **The `actor_role` filter is a compare on the DENORMALIZED `download_audit.actor_role` column, NOT a users JOIN** —
    so a row whose actor account was later deleted (`actor_user_id` FK SET NULL) **still matches its recorded role**
    (the whole point of the audit outliving the account). `count_recent` applies byte-identical predicates to
    `list_recent`, so "Showing X–Y of N" stays honest.
  - No new index — the existing `(school_id, created_at)` composite serves the date-range scan.

### Frontend — the filter UI + a bounded client-side CSV export
- `audit/page.tsx` reworked to the students-page **URL-backed** pattern: an `AuditContent` inner wrapped in
  `<Suspense>` (so `useSearchParams`/`useUrlParams` doesn't break the static prerender — `/audit` stays `○`), inside
  the preserved `RoleGate allow={["school_admin"]}`. Filters (`event`/`student`/`role`/`from`/`to`/`offset`) live in
  the URL; **any filter change resets `offset` to 0 in the same `set()` call.** Controls: Event + Student `<select>`s
  (bounded to the first `PICKER_LIMIT=200` by name), a **Role** `<select>` (All roles / School admins / Teachers /
  Students), and a from/to date range (`<input type="date">` → inclusive UTC day-boundary ISO). A **client-side CSV
  export** (`getDownloadLog` walked in bounded 200-row pages, capped at 10,000, using the *current* `filterParams`;
  reuses `toCsv`/`saveCsv`) → `access-log-{date}.csv` (When / Actor email / Actor role / Event / Photo / Student).
  Extended `useDownloadLog`/`getDownloadLog` with the new params.

## Correctness invariants (verified — R1 SHIP)

- **Tenant isolation unchanged:** `school_id` from `tenant_of(actor)` (token); every new filter is an additive AND on
  the already-`school_id`-scoped query (the first WHERE is always `school_id == sid`), so no filter combination widens
  scope. A malformed `event_id`/`student_id` → `opt_uuid` → `[]`/`0` (no 500, no cross-tenant probe).
- **Deleted-actor survival** (proven by a gated PG test that deletes the actor then re-filters), the **2× boundary
  422**, **list/count filter parity**, and the **bounded + tenant-scoped + filter-consistent** export (each page is a
  `bffFetch` carrying `audit:view` + the token; terminates on a short page / `offset >= total` / the 10k cap).

## Files changed (11, no new files)
Backend: `domain/ports.py` · `adapters/repositories/postgres_download_audit.py` · `services/audit_service.py` ·
`api/routers/audit.py` + tests (`backend_fakes.py`, `test_audit_service.py`, `test_audit_routes.py`,
`tests/adapters/test_postgres_repos.py`). Frontend: `lib/api/endpoints.ts` · `lib/hooks/use-audit.ts` ·
`app/(school)/audit/page.tsx`.

## Verification

- **Backend:** ruff + mypy clean · **pytest 670 passed / 47 skipped** (gated PG skips without `BE_TEST_DATABASE_URL`)
  · layering clean. The gated download-audit round-trip was extended with a real-SQL date-range window + an
  `actor_role` filter incl. the **deleted-actor-still-matches** assertion, verified on a **throwaway `bp28a_migtest`**
  DB (dropped; dev `app` DB never targeted).
- **Frontend:** lint + tsc + `next build` clean; `/audit` stays `○` (static) via the Suspense boundary.
- **2× review→fix loop:**
  - **R1 (correctness): SHIP, 0 blockers, 0 should-fix.** Verified tenant safety, the denormalized-column `actor_role`
    filter (deleted-actor survival), the 2×422, list/count parity, the static prerender, and the bounded/tenant-scoped
    export. Two NITs, both correctly out of scope: the picker 200-cap (by design) and CSV **formula-injection** — the
    latter is a **pre-existing, app-wide** property of the shared `toCsv`, and guarding it there would corrupt
    `token_urlsafe` temp passwords in the credential CSVs (they can start with `-`/`_`), so it is a documented app-wide
    limit, not fixed here.
  - **R2 (edge/a11y/copy): 0 blockers.** Confirmed labelled controls (≥ students-page bar), the differentiated
    empty-with-filters state, and the export busy-state. Applied its 4 should-fixes: a **capped-export toast** ("the
    first 10,000 — narrow the range"), a **picker-truncation hint** ("Showing first 200 — filter by date"), the
    **unified "Role"** filter naming (was "Downloaded by" / 4 names for one axis), and a **"Date filters use UTC"** hint.

## Honest limits (documented)

- **Date filters are UTC day-boundaries** while timestamps display in local time — a school far from UTC gets UTC-day
  windows (hinted in the UI; noted here). Local-day boundaries are a future refinement.
- **The event/student pickers show the first 200** (a bounded `<select>`, not a typeahead) — surfaced with an
  in-dropdown hint; refine by date/the other axes past 200. A searchable picker is the scale-up.
- **CSV export is client-side, bounded at 10,000** rows (a bounded page loop) — a truncated export now says so; a
  server streaming export is the documented scale-up.
- **CSV formula-injection** is an app-wide shared-`toCsv` property (unescaped leading `= + - @`) — not fixed here
  because the shared guard would corrupt credential-CSV passwords; the audit CSV columns are staff-set (name/email/
  event), a low-risk vector.
- **Offset pagination** (keyset is the >10K-row scale-up — the standing house limit).

## Next

**28b — the admin-action audit** (who disabled/deleted/re-enrolled/re-invited a student/teacher, changed a school) — a
new `admin_action_audit` table (**migration `0020`**, mirroring BP8b) + write-hooks inside the single-writer service
methods (so BP27's bulk loops are audited for free) + a second FE audit tab, reusing `audit:view`. **One owner
decision to confirm first** (flagged by the plan-review): whether a `student_deleted` audit row may retain the deleted
student's **name/email** (governance accountability) or store **id-only** to preserve BP8e's "delete means gone" —
default will be **id-only** (privacy-preserving) unless the owner prefers full-identity retention. Then the optional
**A15** (teacher-cap visibility). A slice starts only on owner pick + scope re-confirm.
