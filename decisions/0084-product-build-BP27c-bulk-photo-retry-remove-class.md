# 0084 — Product Build BP27c: Bulk-photo retry/overwrite + bulk-remove-from-class

- **Date:** 2026-08-30
- **Status:** implemented (BE + FE gates green; 2× review→fix loop clean). **27a/27b committed (`1c8f1d1`/`9aaba83`); 27c
  not yet committed** (awaiting owner review). **BP27 is now complete (a, b, c).**
- **Phase:** **BP27c** — the third & final slice of **BP27 (Bulk operations parity)**, Round-4 findings **R4-A07**
  (bulk-photo enroll had no retry-failed + silently overwrote enrolled students) + **R4-A10** (no
  bulk-remove-from-class). **BE + FE — no migration, no ML change, no new dependency, no new permission, no new env
  var.**

## Context

The last two BP27 gaps, mostly FE:
- **Bulk-photo retry-failed (R4-A07):** the BP10 `BulkPhotoDialog` had no "retry failed" (unlike the event uploader,
  which got it in BP19d) — a mid-batch failure meant re-picking everything.
- **Bulk-photo overwrite-confirm (R4-A07):** a matched student already `enrolled` was **silently overwritten** on
  run ("Already enrolled — will replace") with no choice and no confirm.
- **Bulk-remove-from-class (R4-A10):** the students bulk bar had "Assign to class" but no inverse.

**Workflow (owner-directed multi-agent pipeline):** planning agent (consolidated the 27c spec against the current
post-27a/27b code) → plan-review agent (**resolved the one open question — a `services→services` import of
`BulkActionResult` is layering-clean**; hardened the firedRef/keep-existing/tenant details) → implementation agent →
2× review loop (R1 correctness, R2 edge/a11y/copy).

## Decision

### Item 1 — Bulk-photo retry-failed (FE, mirrors BP19d)
`lib/hooks/use-bulk-photo-enroll.ts` gains a `useRef<Map<id, BulkEnrollInput>>` (rewritten per-batch in `run()` — row
ids are the per-batch index, so a new batch overwrites the same keys, and `retryFailed` only looks up the **current**
items, always resolving a live handle), an extracted **`runPool(entries)`** (reads from its **argument**, not `items`
state, so `run` and `retryFailed` reuse one implementation), and **`retryFailed()`** which re-runs the pool over BOTH
`status==="error"` AND enroll-failed `done` rows (`done && enrollmentStatus !== "enrolled"` — matching
`summary.failed`), clearing `error`/`progress`/`enrollmentStatus` on re-queue. `bulk-photo-dialog.tsx` renders a
**"Retry failed (N)"** button in the RunStep, gated on `!isRunning && summary.failed > 0` — the **single-pool
invariant** (the button only mounts once the prior pool's `Promise.all` has drained, so no two pools ever touch the
same item). A parent `handleRetry = () => { firedRef.current = false; retryFailed(); }` re-arms the one-shot
list-refresh effect (`firedRef` lives in the dialog, not the hook). Re-running an enroll-failed `done` row is
orphan-safe (`setStudentReferencePhoto` overwrites + best-effort-reaps the prior object). Honest copy: a `no_face`
failure "won't change on retry — replace the photo instead."

### Item 2 — Overwrite-confirm / keep-existing (FE only, no backend change)
`Row.keepExisting` (default `false` = **Replace**, keeping today's behavior — flipping the default would silently drop
photos a user intentionally dropped). A per-row **Replace | Keep existing** radiogroup renders **only** for
`studentId && enrollmentStatus==="enrolled"` (native radios grouped by name → free keyboard semantics); `assign`/`skip`
reset it. **`start()` excludes kept rows** (`!(enrollmentStatus==="enrolled" && keepExisting)`) so a kept row is never
turned into a `BulkEnrollInput` → `setStudentReferencePhoto` is never called for it (this *is* the mechanism — no
backend change). An **`effectiveCount`** (matched − kept) drives the "Upload N" label + the disabled guard + a "K
kept" summary + the all-kept empty toast; a batch **overwrite `ConfirmDialog`** (naming `effectiveReplacing`) fires
before the run only when ≥1 enrolled row would be replaced — closing R4-A07's "silent" complaint without a surprising
default flip.

### Item 3 — Bulk-remove-from-class (small BE loop + FE)
- **`ClassService.remove_students_bulk(*, school_id, student_ids) -> list[BulkActionResult]`** — a best-effort loop
  over the tested single-writer `set_student_group(..., group_id=None)` (**Option B** — `set_group_bulk` can only SET
  a non-null group, so it can't clear; the loop composes the shipped primitive, no new repo method). A foreign id →
  `NotFoundError` from the tenant-scoped `get` **before any write** → per-row `error`; the batch never aborts;
  PII-safe id-only logging. Reuses `BulkActionResult` from `student_service` (a `services→services` import, verified
  layering-clean).
- **`POST /v1/students/bulk-remove-class`** (`student:manage`, `tenant_of(actor)`, `BulkIdsRequest` →
  `BulkActionResponse`, in the literal block **before** `GET /{student_id}`) delegating to
  `container.class_service().remove_students_bulk(...)`.
- FE: `bulkRemoveStudentsFromClass` + a **"Remove from class"** action in the students bulk bar (gated on
  `classes.length>0` like Assign, acts on `targetIds` so it spans the `all`-mode snapshot, `afterBulkMutation` since a
  class change is list-visible via the `student_group_name` sub-label).

## Files changed (7)
`services/class_service.py` · `api/routers/students.py` · `tests/test_bp27_bulk.py` (+8 bulk-remove tests) ·
`frontend/lib/hooks/use-bulk-photo-enroll.ts` · `frontend/components/students/bulk-photo-dialog.tsx` ·
`frontend/lib/api/endpoints.ts` · `frontend/app/(school)/students/page.tsx`.

## Verification

- **Backend:** ruff + mypy clean · **pytest 664 passed / 47 skipped** (gated skip without `BE_TEST_DATABASE_URL`) ·
  layering clean. The 8 new bulk-remove tests prove: removes-many + only-selected, a foreign id → `error` +
  batch-continues + **the foreign student still classed in its own school** (service + an end-to-end route test
  through `tenant_of`), the round-trip clears the class, 401/403 (a student token → 403) / 422 (empty + over-cap), and
  the **route-ordering regression** (`bulk-remove-class` isn't shadowed by `/{student_id}`).
- **Frontend:** lint + tsc + `next build` clean; `/students` stays `○` (static). The retry/overwrite correctness is
  carried by tsc + the mirrored BP19d single-pool invariant (no FE test harness exists).
- **2× review→fix loop:**
  - **R1 (correctness): SHIP, 0 blockers, 0 should-fix.** Verified the single-pool invariant (retry flips to `queued`
    before `runPool`; `runPool` reads its arg; the `!isRunning` mount gate prevents overlap), the `firedRef` re-arm,
    the retry set (error + enroll-failed), keep-existing = no upload, and the bulk-remove tenant path (404-before-write
    with a real foreign-school student) + route ordering. The nested confirm is a working modal-over-non-modal. Applied
    its 2 comment-accuracy NITs (the `inputsById` and `runPool` invariant docs).
  - **R2 (edge/a11y/copy): 0 blockers.** Confirmed the overwrite-confirm count/copy, the retry `no_face` honesty, the
    native-radio radiogroup semantics, and the all-kept/re-pick/retry-partial edges. Applied its 2 should-fixes: the
    **"Remove from class" toast honesty** (→ "Cleared class for N students" — the backend returns `ok` even for a
    student who wasn't in a class, so "Removed N" over-claimed) and a **more-visible radio focus ring** (enlarged +
    offset).

## Honest limits (documented)

- **Retry re-uploads a fresh object** each time (new storage key; the prior object is best-effort-reaped) — not a
  cheap re-attach; a `no_face` row won't self-heal (replace the photo instead).
- **Keep-existing default is Replace** — a user preserves a photo by opting out per-row; the batch confirm makes the
  replace informed.
- **Bulk-remove is a per-id loop** (bounded ~800, capped 1000) — a set-based `UPDATE … SET NULL` is the documented
  scale-up. Removing a student who wasn't in a class is a harmless no-op `ok` (hence the "Cleared class for" copy).

## Next

**BP27 (Bulk operations parity) is complete (a, b, c).** The remaining Round-4 tiers: **BP28** governance/audit ·
**BP29** teacher coherence · **BP30** review tools · **BP31** onboarding/copy. A phase starts only on owner pick +
scope re-confirm.
