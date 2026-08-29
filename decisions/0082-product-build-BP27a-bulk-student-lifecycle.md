# 0082 — Product Build BP27a: Bulk student lifecycle + select-all-matching

- **Date:** 2026-08-30
- **Status:** implemented (BE + FE gates green; 2× review→fix loop clean). **Not committed** (awaiting owner review).
- **Phase:** **BP27a** — the first slice of **BP27 (Bulk operations parity)**, the first Tier-1 phase off the Round-4
  staff/admin review ([`product/08`](../product/08-product-review-round-4-staff-admin.md) findings **R4-A04**,
  **R4-A06**) + roadmap ([`product/09`](../product/09-improvement-roadmap-round-4.md)). **BE + FE — no migration, no
  ML change, no new dependency, no new permission, no new env var.**

## Context

At ~800-student scale every *bulk* affordance stopped one step short: a student could be disabled/deleted only
**one-at-a-time** on the detail page (BP18d/BP8e single-writes), and multi-select acted on the **loaded page only**
(no "select all matching the filter"). BP27 closes those cliffs by **composing the already-tested single-writes** as
best-effort batch loops (never new domain logic).

**Slicing (owner-approved shape, refined by plan-review):** BP27 splits into **27a** (this — bulk disable/enable +
delete + select-all-matching), **27b** (the shown-once bulk-credentials surface — student bulk-*resend* + staff CSV
invite, sharing one credentials dialog — pulled out of 27a on the reviewer's advice so the secret surface is
reviewable on its own), and **27c** (bulk-photo retry + overwrite-confirm + bulk-remove-from-class).

**Workflow used (owner-directed multi-agent pipeline):** a **planning** agent produced a code-grounded sliced plan →
a **plan-review** agent hardened it against the code (caught 2 blockers pre-code: the `delete_student` partial-failure
window + the `/ids` param-parity requirement) → an **implementation** agent built 27a + ran the gate → a **2× review**
loop (R1 correctness, R2 edge/a11y/copy) with fixes applied.

## Decision (all composing tested single-writes)

### Backend — best-effort loops + the select-all id-scan
- **`StudentService.bulk_set_status` / `bulk_delete_students`** (`student_service.py`) — pure loops over the existing
  `set_status` / `delete_student`, each wrapped per-row in try/except: success → `ok`, **any** exception (a foreign
  id's `NotFoundError`, an ML-down `UpstreamError`, anything) → `error`, **the batch never aborts**; PII-safe id-only
  logging. Returns a frozen `BulkActionResult(student_id, status)` list.
- **`ListingService.list_student_ids`** — the select-all-matching primitive: one call to the **existing**
  `StudentRepository.list_ids` with the **identical** filter args the page path uses (so the id set is exactly what
  the list shows), tenant-scoped, id-only. No new repo method; the read is bounded by a school's student count
  (~800), the *action* request is capped by `_MAX_BULK_IDS`.
- **Routes** (`api/routers/students.py`, all `student:manage`, `tenant_of(actor)`, placed in the literal block
  **before** `GET /{student_id}`): `GET /v1/students/ids` (param signature = a copy of `list_students` minus
  sort/dir/limit/offset, incl. `resolve_focus_group_ids(container, actor, mine)`), `POST /v1/students/bulk-status`,
  `POST /v1/students/bulk-delete`.
- **Schemas** — `_MAX_BULK_IDS = 1000` (a module const, no new env var; covers a full ~800-student school in one
  request → 422 over cap, `min_length=1` → 422 empty); `BulkIdsRequest` / `BulkStatusRequest`; the
  `BulkActionResponse` envelope; `StudentIdsResponse {ids, total}`.

### Frontend — extend the BP25 multi-select bar (not rebuild)
- A discriminated **`Selection`** model: `{mode:"ids", ids:Set}` (hand-picked, stale-safe — the acted-on set is
  intersected with the loaded rows) | `{mode:"all", ids:string[], total}` (the whole server snapshot, spanning pages).
- The **checkbox column widens** to show whenever `total > 0` (disable/delete don't need classes); the **"Assign to
  class"** sub-control stays gated on `classes.length > 0`.
- Bar actions: **Disable / Enable** (`bulk-status`), **Delete** (behind a `ConfirmDialog` echoing the count +
  BP8e-accurate irreversibility copy), plus the existing **Assign**. A **"Select all N matching"** control appears
  once the whole loaded page is picked and more rows match — `getStudentIds(currentFilters)` → `mode:"all"`.
- Selection **resets on any filter/search change** (adjust-state-during-render, not an effect) so an `all` snapshot
  never carries across filters — **but survives a re-sort** (sort only reorders the same matching set). Every action
  runs `mutate()` + `mutateDashboard()`, clears the selection, and toasts **honestly** (full "Disabled N students" vs
  partial "Disabled X of N — Y couldn't be updated/deleted"). A single **`bulkAction`** state drives the
  disabled/double-submit guard **and** spins only the *clicked* button; an in-flight `role="status"` "· working…"
  announces progress to assistive tech.
- `endpoints.ts`: `getStudentIds` reuses `listQuery` (drift-proof — it can't diverge from `getStudents`, protecting
  the "identical id set" invariant) + `bulkSetStudentStatus` / `bulkDeleteStudents`.

## Correctness invariants (verified)

- **Tenant isolation is inherited, not re-implemented:** every looped single-write resolves the student via a
  `school_id`-scoped `get_student` **before any write**, so a foreign/missing id is a per-row `error`, never a
  cross-tenant write. `school_id` comes from `tenant_of(actor)` (token) on all three routes — never body/URL.
  `GET /students/ids` reuses the identical tenant-scoped WHERE as the list (can't return a foreign id) and threads
  `mine`-scope identically (an admin's `mine` is ignored — no escalation).
- **Best-effort / no-abort:** one failing row (foreign id, ML-down) never aborts the batch.
- **The `matches` seam is untouched** — bulk delete loops the per-student ML delete RPC; select-all uses `list_ids`
  (a backend-table id scan). No SQL join to `matches`.
- **Bulk delete is best-effort (a deliberate contract difference from single-delete):** single `delete_student`
  surfaces an ML-down as **502** so the operator retries; the batch converts that to a per-row `error` so it never
  aborts. `delete_student` is ordered **ML-first** (so a partial row leaves no orphaned ML data), and the ML `DELETE`
  is **idempotent** (verified: FAISS/`matches`/detection deletes are no-ops on an absent student → 204), so a row
  that errored after removing its ML footprint **self-heals on retry**. Locked in by a test.

## Files changed (7 + 1 new test)
`services/backend/src/backend/services/student_service.py` · `services/listing_service.py` ·
`api/schemas/students.py` · `api/routers/students.py` · `frontend/lib/api/types.ts` · `frontend/lib/api/endpoints.ts`
· `frontend/app/(school)/students/page.tsx` · **new** `services/backend/tests/test_bp27_bulk.py` (18 tests).

## Verification

- **Backend:** ruff clean · mypy clean (172 files) · **pytest 635 passed / 47 skipped** (gated Postgres skips without
  `BE_TEST_DATABASE_URL`) · layering clean. The 18 BP27 tests prove: foreign-id-untouched (service + an **end-to-end
  route** test through the full token→`tenant_of`→service stack), ML-failure isolation (batch continues), the
  retry-self-heal, `/ids` = the page's id set for a status filter + `mine`-scope + foreign-school exclusion,
  401/403/422, the cap, and the route-ordering regression guard.
- **Frontend:** lint + tsc + `next build` clean; `/students` stays `○` (static, `<Suspense>` preserved).
- **2× review→fix loop:**
  - **R1 (correctness): SHIP.** Tenant isolation airtight, best-effort loops never abort, route ordering guarded, the
    FE `Selection` machine stale-safe across every traced transition, caps/schema/confirm in place. Applied its 3
    findings: an **end-to-end cross-tenant route test**, a `getStudentIds`↔`listQuery` drift fix (reuse, don't
    re-implement), and a docstring note on the `>_MAX_BULK_IDS` edge.
  - **R2 (edge/a11y/copy): no blockers.** Delete copy accurate to BP8e; honest partial toasts pluralized. Applied its
    3 should-fixes + 1 nit: an **in-flight `role="status"` announcement**, a **spinner on the clicked** Disable/Enable
    button (via the single `bulkAction` source, so un-clicked buttons don't spin), **sort no longer wipes the
    selection**, and delete's partial toast now says "deleted" not "updated".

## Honest limits (documented)

- **Bulk delete is best-effort + irreversible** — a partial run reads "Deleted X of N; Y couldn't be deleted" and the
  Y remain (retryable); no undo (BP16 erasure-undo stays parked). The confirm echoes the exact count (incl. the
  all-matching N).
- **Select-all-matching is a snapshot at click time** — a concurrent create/delete is handled by the best-effort
  per-row loop (a since-deleted id → a skipped `error`; a since-created student isn't included). Cleared on any
  filter change.
- **`_MAX_BULK_IDS = 1000`** bounds a single request; a hypothetical >1000-student school selecting-all would 422 on
  the follow-up POST (narrow the filter) — not reachable at v1 scale.
- **Enable + Disable are both always shown** (you can't know from a loaded page whether an "all" snapshot is uniformly
  enabled); the idempotent `set_status` makes the no-op direction harmless.
- A set-based bulk `UPDATE`/`DELETE` is the documented scale-up; the loops (which touch `users` rows + ML RPCs + object
  storage — no single SQL statement expresses them) are correct and fine at ~800.

## Next

- **27b** — the shown-once bulk-credentials surface: student **bulk-resend-invite** (closes **R4-A05**) + **staff CSV
  invite** (closes **R4-A13**), sharing one `BulkCredentialsDialog` (Download-CSV + close-guard).
- **27c** — bulk-photo **retry-failed** + **overwrite-confirm** (R4-A07) + **bulk-remove-from-class** (R4-A10).
- Then the remaining Round-4 tiers (BP28 governance/audit · BP29 teacher coherence · BP30 review tools · BP31
  onboarding/copy). A phase/slice starts only on owner pick + scope re-confirm.
