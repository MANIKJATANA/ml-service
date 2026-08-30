# 0086 — Product Build BP28b: Admin-action audit (the governance actor trail)

- **Date:** 2026-08-30
- **Status:** implemented (BE + FE gates green; 2× review→fix loop clean). **Committed + pushed.**
- **Phase:** **BP28b** — the second slice of **BP28 (Governance & audit completeness)**, Round-4 finding **R4-A25**
  (governance-lifecycle actions — who disabled/deleted/re-enrolled/re-invited a student or teacher, who edited a
  school — left **no record**). **BE + FE — migration `0020`** (a new backend-owned table); **no ML change, no new
  dependency, no new permission** (reuses `audit:view`), **no new env var.**

## Context

BP8b gave *downloads* an append-only audit; the governance surface had none. A student silently vanished (delete),
a teacher's login flipped disabled↔enabled, an invite was re-sent, a school's cap/status changed — and nothing said
**who** or **when**. 28b adds an append-only `admin_action_audit` table written **best-effort inside the single-writer
service methods**, so BP27's bulk loops (which thread the actor down and call those same single-writers per row) are
**audited for free**, and surfaces it as a second tab on the existing `/audit` page.

**Workflow (owner-directed multi-agent pipeline):** planning agent (grounded in the BP8b `download_audit` stack as the
structural template) → plan-review agent (confirmed the single-writer write-hook approach audits BP27 bulk for free,
and flagged the one owner decision below) → implementation agent → 2× review loop.

## Decision

### Migration `0020` — `admin_action_audit` (mirrors BP8b's `download_audit`)
Columns: `id` · `school_id` (FK→schools **CASCADE**) · `actor_user_id` (FK→users **SET NULL** — the trail outlives the
account) · `actor_role` (denormalized, CHECK ∈ 4 roles) · `action` (CHECK ∈ the 11 values below) · `target_type`
(CHECK ∈ `student`/`staff`/`school`) · `target_id` (nullable, **NO FK** — a heterogeneous student/staff/school id,
exactly as `match_corrections` carries no FK to the ML-owned `matches`) · `target_label` (nullable, a human label
captured at write time) · `created_at`. **Four composite indexes** each prefixed `(school_id, …, created_at)`: the
school-wide log + target / actor / action drill-downs. down_revision `0019`; fully reversible (drop indexes → table).
Verified **up→down→up on a throwaway `bp28b_migtest`** (dropped; dev `app` DB never targeted).

### Domain (import-pure) + port
- `AdminAction` StrEnum (11): `student_created` · `student_disabled` · `student_enabled` · `student_deleted` ·
  `student_reenrolled` · `student_invite_resent` · `staff_created` · `staff_disabled` · `staff_enabled` ·
  `staff_invite_resent` · `school_updated`. `AdminActionTargetType` StrEnum (`student`/`staff`/`school`). Frozen
  `AdminActionAuditEntry` VO. The CHECK constraints are kept **lockstep** with the enums.
- `AdminActionAuditRepository` port: `record(...)` (one row, owns its own transaction) + `list_recent`/`count_recent`
  (school-scoped, newest-first, filters: `action`/`target_type`/`target_id`/`actor_user_id`/`created_from`/
  `created_to`) — the same filter shape BP28a gave downloads.

### Adapter + read service
- `adapters/repositories/postgres_admin_action_audit.py` — the append-only writer + the filtered/paginated reads
  (`created_at DESC, id DESC` stable sort). Wired in `registry.py` + a memoized `container.py` builder.
- `services/admin_action_audit_service.py::AdminActionAuditService.school_action_log` → `AdminActionLogPage` of
  `AdminActionView` — joins the actor's **current** email from the backend's OWN `users` rows, **batched in-Python
  (no N+1), never a cross-service SQL join** (mirrors `AuditService`). A deleted actor reads back
  `actor_user_id`/`actor_email = None` while the denormalized `actor_role` + `target_label` still show what happened.

### Write-hooks inside the single-writers (best-effort — the load-bearing design choice)
A private `_record_action(...)` helper on **both** `StudentService` and `OnboardingService` calls
`AdminActionAuditRepository.record` wrapped in `try/except Exception → _log.warning("admin_action_audit_record_failed",
school_id=…)`: **a failed audit must NEVER block or roll back the mutation it trails.** This is safe because each repo
method owns its own transaction — the mutation has already committed before the (separate-transaction) audit write
runs, so swallowing here cannot roll it back. The helper **skips the write when `actor_role is None`** (a caller not
threaded through) rather than guessing. Because BP27's bulk loops call these exact single-writers per row (threading
the actor down), **every bulk disable/enable/delete/resend is audited row-by-row for free** — no bulk-specific code.
Hook placements chosen to record the *effective* action only:
- `set_status` records **inside** `if student.status is not status:` (a no-op status set records nothing).
- `set_staff_status` records **after** the no-op early-return **and** the last-active-admin guard (a refused disable
  records nothing).
- `update_school` records against the **TARGET** school_id (a platform admin has `school_id = None`, so the row is
  keyed to the school actually edited, not the actor's null tenant).
- `delete_student` records `target_type=student, target_id=student.id, **target_label=None**` — **id-only** (see the
  owner decision below); the name is captured pre-delete but deliberately not stored.

### Route + FE
- `GET /v1/audit/admin-actions` on the existing `audit.py` router (`audit:view`, tenant strictly from the token). Date
  params typed `datetime | None` and `action`/`target_type` typed as their enums → a malformed value **422s at the
  FastAPI boundary** (the BP28a hardening, reused).
- `frontend/lib/audit/actions.ts` (new) — an `ACTION_LABELS` humanizer for the 11 enum values + `ACTION_OPTIONS` /
  `TARGET_TYPE_OPTIONS` for the filter `<select>`s.
- `frontend/components/ui/tabs.tsx` (new) — a thin Radix Tabs wrapper (`Tabs`/`TabsList`/`TabsTrigger`/`TabsContent`),
  giving the audit page roving-tabindex + arrow-key nav + correct `tab`/`tabpanel` aria wiring.
- `audit/page.tsx` reworked to **two tabs** (Downloads / Admin actions, `?tab=` URL-backed inside the existing
  `<Suspense>` so `/audit` stays `○` static), each with its own URL-backed filters + a client-side CSV export. The
  admin-actions tab's Target cell renders `target_label`, falling back to **"Deleted student"** for a null-label
  `student_deleted` row (and "—" otherwise). `types.ts` / `endpoints.ts` / `use-audit.ts` gain the admin-actions
  read.

## Owner decision (flagged by plan-review, resolved by default)

**A `student_deleted` audit row stores the student id ONLY (`target_label=None`), not the name/email** — preserving
BP8e's "delete means gone" (a deleted student's identity must not linger in the audit). This is the privacy-preserving
default; the alternative (retain name/email for governance accountability) is a one-line change to the delete hook if
the owner later prefers full-identity retention. Every *other* action keeps its human `target_label` (the account
still exists).

## Correctness invariants (verified — R1 SHIP)

- **Tenant isolation:** `school_id` from `tenant_of(actor)` on both the reads and the write-hooks (except
  `update_school`, keyed to the target school by design); `target_id` has no FK but is only ever read back within its
  `school_id` scope. No cross-service SQL join (actor email composed in-Python).
- **Best-effort audit never corrupts a mutation:** the per-method own-transaction boundary + the `try/except` swallow
  means a down audit table degrades to "no trail", never to a failed disable/delete.
- **Effective-action recording:** no-op status sets, refused (last-admin) disables, and un-threaded callers record
  nothing.
- **Actor-threading blast radius contained:** the 8 affected test-builder files pass a `FakeAdminActionAuditRepo()` to
  the `StudentService`/`OnboardingService` constructors; mypy (176 files) confirms no signature mismatch anywhere.

## Files changed
New (5): `adapters/repositories/postgres_admin_action_audit.py` · `services/admin_action_audit_service.py` ·
`db/migrations/versions/0020_admin_action_audit.py` · `tests/test_bp28b_admin_action_audit.py` ·
`frontend/lib/audit/actions.ts` (+ `frontend/components/ui/tabs.tsx`). Modified: `domain/models.py` ·
`domain/ports.py` · `db/models.py` · `services/student_service.py` · `services/onboarding_service.py` ·
`api/routers/{audit,students,staff,schools}.py` · `api/schemas/audit.py` · `wiring/{registry,container}.py` +
8 test-builder files; FE `audit/page.tsx` · `lib/api/{types,endpoints}.ts` · `lib/hooks/use-audit.ts` ·
`components/ui/app-shell.tsx`.

## Verification

- **Backend:** ruff + mypy clean (176 files) · **pytest 705 passed / 48 skipped** (gated PG skips without
  `BE_TEST_DATABASE_URL`) · layering clean. `test_bp28b_admin_action_audit.py` covers the record + filtered reads +
  the actor-email compose (incl. deleted-actor → None) + the effective-action hook placements; a **gated real-Postgres
  round-trip** in `test_postgres_repos.py` proves record → list/count → filters → newest-first → tenant scope +
  **actor SET NULL survival**, on a throwaway `bp28b_migtest` (dropped; dev `app` untouched). (A known **pre-existing**
  BP8c in-memory rate-limit suite-ordering flake can surface on a long full-suite run — confirmed not introduced here;
  the clean run = 705.)
- **Frontend:** lint + tsc + `next build` clean; `/audit` stays `○` (static) via the Suspense boundary.
- **2× review→fix loop:**
  - **R1 (correctness): SHIP, 0 blockers.** Verified the best-effort own-transaction safety, tenant scoping on reads +
    every write-hook, the effective-action placements, no cross-seam join, and the actor-threading mypy cleanliness.
    Applied its one NIT (thread `school_id=school_id` into both warning log calls for a debuggable failure).
  - **R2 (edge/a11y/copy): 0 blockers, 2 should-fix — both applied:** replace the hand-rolled `role="tablist"`
    `TabButton` with the app's **Radix `Tabs`** (arrow-key nav + `tabpanel` wiring), and render a muted **"Deleted
    student"** for a null-label `student_deleted` row instead of a bare "—" (table cell + CSV).

## Honest limits (documented)

- **`student_deleted` is id-only** (name/email deliberately not retained — BP8e "delete means gone"); the row proves
  *a student was deleted by X at T*, not which student by name. Full-identity retention is a one-line override.
- **Actor email is the CURRENT email**, joined at read time — a since-renamed actor shows their new email (the
  denormalized `actor_role` is the point-in-time fact; the email is a convenience join).
- **Best-effort write:** a governance action whose audit write fails is logged (`admin_action_audit_record_failed`)
  but not retried — the mutation still succeeds. A guaranteed-audit (transactional-outbox) trail is the scale-up.
- **CSV export** shares BP28a's bounded-10k client-side loop + the app-wide `toCsv` formula-injection limit.
- **Offset pagination** (the standing house limit).

## Next

**BP28 is complete (28a + 28b).** The optional **A15** (teacher-cap visibility — surface a school's used/remaining
teacher seats to the school-admin) is the small BP28 add-on. Then the remaining Round-4 tiers: **BP29** teacher
coherence · **BP30** review-loop power tools · **BP31** onboarding feedback loop & copy polish — each through the full
Plan → plan-review → implement → 2× review pipeline, committed + pushed on completion (autonomous). A slice starts only
on owner pick + scope re-confirm (the standing autonomous authorization covers the R4 roadmap order).
