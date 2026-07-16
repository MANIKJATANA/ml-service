# 0045 — Product Build BP7b: Reference-photo enrollment quality feedback

**Date:** 2026-07-16
**Status:** Accepted

## Context

The second BP7 sub-phase (after BP7a's setup checklist; see [decisions/0044](0044-product-build-BP7a-setup-checklist.md)
for the four-slice decomposition). Today a failed enrollment shows a bare **"Failed"** pill with no reason — staff
can't tell a bad photo from a transient ML outage, so failures don't self-correct (fails **T8/P6**). The information
already exists and is thrown away: the ML enroll response carries a per-photo `detail`/status, the backend's HTTP
client already parses it into `PhotoResult.detail`, and then `_run_enroll` **discards it** (only checking
`embeddings_stored >= 1`). BP7b captures it. **Backend + frontend; one migration (`0007`); no ML change.**

Key finding from the ML code (`orchestration/enrollment.py`): **`multiple_faces` is not a failure** — the ML enrolls
the *largest* face and stores an embedding. So a failed enrollment (`embeddings_stored == 0`) is only ever **no-face**
or a per-photo **error**; plus the whole-call **ML-unavailable** (the `httpx.ReadTimeout`/`UpstreamError` seen in the
wild on a cold ML container). That gives a clean 3-value reason set.

## Decisions

### 1. A closed `EnrollmentFailureReason` enum, captured in the service, cleared on success
New `EnrollmentFailureReason` StrEnum `{no_face, ml_unavailable, error}`. `StudentService._run_enroll` derives it:
- **success** (`embeddings_stored >= 1`) → `ENROLLED`, reason `None`;
- **response, 0 embeddings** → `FAILED` + `_reason_from_outcome` (the single reference photo's first result: `no_face`
  when the ML detected none, else the generic `error`);
- **exception** (`UpstreamError` — ML down / timed out) → `FAILED` + `ML_UNAVAILABLE` (transient — retry).

The reason is **always** passed to `set_enrollment(status=…, failure_reason=…)`, so a successful (re-)enroll **clears**
any prior reason (never lingers stale). Best-effort persistence is unchanged — a status-write failure still can't fail
account creation (0026). `_reload` threads the reason into its read-miss fallback so the response matches what was
persisted. The cross-service `"no_face"` wire value (the backend must not import `ml_service` — layering) is pinned as
a named constant `_ML_STATUS_NO_FACE` with a comment + a mapping test (incl. a defensive `multiple_faces`→`error` pin).

### 2. Migration `0007` — nullable `students.enrollment_failure_reason`
Adds a nullable `String` column + a CHECK (`IS NULL OR IN ('no_face','ml_unavailable','error')`), lockstep with the
domain enum and the ORM model. Backend chain only (`alembic_version_backend`); `0006`→`0007`; reversible (drop
constraint + column). Exposed additively on `StudentResponse` (`enrollment_failure_reason: … | None`), inherited by
`StudentListItem` via its `model_dump()` spread.

### 3. Frontend — a tailored explanation + fix
- **Student detail** (`/students/[id]`): an `EnrollmentFailureNote` (`role="alert"`, an AA-passing `text-error` tint)
  replaces the old generic sentence — a reason-specific **title + fix** from `ENROLL_FAILURE_HELP`.
- **Students list**: a **compact reason** under the "Failed" pill (`ENROLL_FAILURE_SHORT`, `text-ink-secondary` — not
  the sub-AA `ink-muted`).
- Both degrade gracefully when a `failed` row has a `null` reason (legacy/pre-migration): generic copy / no label, no
  crash. Copy is written from the user's side and matched to the available action (below).

## Honest scope

BP7b is the **diagnosis**. The actual fix for a bad photo — **replacing the reference photo in place** — is **BP7d**
(the "add/replace photo later" work). Until then the detail page's always-present **Re-enroll** button retries the
*same* stored photo, which fixes only `ml_unavailable`; for `no_face`/`error` the fix copy leads with *"Re-enrolling
uses the same photo, so it will fail again — delete and re-add …"* so staff aren't sent down a dead end.

## Verification

- BE gate green: ruff + mypy + **full suite 315 passed / 21 skipped**. New: service tests (no_face / generic-error /
  `multiple_faces`→error / ml_unavailable / success-has-no-reason / successful-reenroll-clears-it), a **route-level**
  assertion that the reason serializes through `StudentResponse` and clears on re-enroll, and a **gated real-Postgres**
  adapter test (set→read→clear round-trip through the column + its CHECK).
- **Migration `0007` verified up → down → up on a throwaway Postgres** (`bp7b_migtest`, created + dropped; the dev `app`
  DB never touched), and the gated adapter tests were run green against it.
- FE gate green: `tsc --noEmit` + `eslint` + `next build`.
- **2× review→fix loop** (two agents). **R1 (correctness): no blockers, all areas clean** — reason derivation, the
  exact `"no_face"` contract, the reversible migration mirroring the model, overwrite/clear semantics, `StudentListItem`
  carrying the field on both ends, graceful FE null-handling. **R2 (edge/quality/a11y/coverage)** confirmed a11y
  (`role="alert"` per the house convention) + contrast + edge cases correct, and its four actionable items were
  applied: the cross-service literal → a named constant, the `multiple_faces`→error contract pin, the route-level
  serialization assertion, and sharper `no_face`/`error` fix copy.

## Follow-ups

**BP7c** (staff lifecycle + invite model) next, then **BP7d** (CSV bulk import — which also lands the in-place
reference-photo **replace** that completes this loop). Optionally, a cross-service contract test pinning the ML
`PhotoStatus` values the backend depends on.
