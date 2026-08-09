# 0067 — Product Build BP18c: School-record lifecycle

- **Date:** 2026-08-07
- **Status:** implemented (gate green; awaiting owner review before commit)
- **Phase:** the third slice of **BP18 (Account recovery & credential safety)** — after BP18a's student recovery
  ([0065](0065-product-build-BP18a-student-credential-recovery.md)) and BP18b's safety net
  ([0066](0066-product-build-BP18b-credential-safety.md)). Closes the Round-3 finding that the **school record was
  write-once** (R3-A1-01).

## Context

The school record had no mutation path in the API or UI: an operator could not rename a school, change its
teacher cap, or suspend/reactivate it — yet `suspended` is a rendered status **and** actively enforced downstream
(`create_teacher` / `student_service._require_active_school` reject a non-active school). So the only way to
change any of it was DB surgery, and the write-once record was the one admin object in the product without a
lifecycle. BP18c gives it one. The `schools` columns (`name`/`max_teachers`/`status`) were already mutable — **no
migration.**

## Decision

Add `PATCH /v1/schools/{id}` (name / max_teachers / status), platform-only.

- **BE:** `SchoolRepository.update(school_id, *, name=None, max_teachers=None, status=None) -> School | None`
  (port + Postgres adapter + fake) — a partial update where only the provided (non-None) fields change (`None`
  leaves the column untouched; `status.value` is written; `updated_at`'s onupdate trips). `OnboardingService.
  update_school` reuses `create_school`'s validation (name strip 1–200, max_teachers ≥1) **only when the field is
  provided**, and 404s a missing school (`school_id` is a client path param on this cross-tenant platform surface,
  so a miss is a 404, not a 400). `PatchSchoolRequest` (all-optional; `Field(ge=1)`/`min_length` + the
  `SchoolStatus` enum give a 422 for bad input before the service). The route sits in the `school:manage`-gated
  schools router.
- **FE:** an **Edit-school** dialog (name + max_teachers, prefilled and re-prefilled on open, mirroring the
  create dialog's integer guard) and a **Suspend / Reactivate** action (suspend confirms first — it blocks new
  provisioning downstream; reactivate is immediate) on the platform school detail; both revalidate `useSchool`
  via `mutate()` (the PATCH returns a rollup-less `SchoolResponse`, so a revalidate — not a cache-set — keeps the
  detail's rollup fresh). The status pill now renders a proper label ("Active"/"Suspended") instead of the raw
  lowercase enum.

## Why

- **No guard on suspend** (unlike BP18b's last-admin disable): suspending is intentional and **reversible** — a
  platform admin can always PATCH `status: active` back — and it removes no one's access, it just gates new
  teacher/student creates (already enforced). So no lockout risk and no guard needed. Lowering `max_teachers`
  below the current teacher count is likewise allowed: the cap is only checked at create time, so it blocks new
  adds without removing anyone (documented in the service docstring).
- **Revalidate, not cache-set:** the PATCH response is a plain `SchoolResponse` (no rollup); writing it into the
  `SchoolWithRollup` cache would drop the rollup, so the FE ignores the return and revalidates.

## Consequences

- No migration, no ML change, no new dependency, no new permission (reuses `school:manage`).
- Verified: backend ruff + mypy + **576 passed / 38 skipped** (+8 BP18c: 5 service — rename+cap, suspend↔
  reactivate, partial-keeps-others, 404, bad-input; 3 route — edit/suspend/reactivate happy-path, unknown-404,
  and a schema-level 422 for a bad status / `max_teachers=0`) + layering; FE lint + tsc + `next build` green.
  2× review loop: **R1** (correctness/security/tenant) — clean, no blockers (partial-update correct, suspend
  needs no guard, route/permission sound, FE re-prefill + revalidate correct); **R2** (edges/coverage/a11y) —
  SHIP → added the route-level 422 test and a cap-lowering docstring clause.
- **Next:** BP18d (session revocation on password change + student disable — the one migration).
