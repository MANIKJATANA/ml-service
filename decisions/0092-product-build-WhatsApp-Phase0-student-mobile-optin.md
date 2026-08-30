# 0092 — WhatsApp Phase 0: student mobile number + WhatsApp opt-in

- **Date:** 2026-08-30
- **Status:** implemented (BE + FE gates green; 2× review loop SHIP). **Not yet committed (awaiting owner review).**
- **Scope:** the first slice of the owner-locked **WhatsApp auto-send** track (direction locked in
  `whatsapp-build-plan.html`; exploration in `whatsapp-plan.html`). Phase 0 adds a **student mobile number** and a
  **WhatsApp opt-in flag**, end to end, so later phases (W1 provider + settings, W2 the send flow) can message a
  student's photos on WhatsApp. **Phase 0 sends nothing** — no provider, no integration, no queue. **BE + FE; one
  migration (`0021`); no ML change, no new dependency, no new permission, no new env var.**

## Context

The owner set the direction: staff select photos (or Select-all) and the system **auto-sends each photo inline** to
the student's WhatsApp via a provider account the platform owns and pays for (Gupshup/Wati; decided at W1). Before any
of that can exist, the app has to **store where to send** — a per-student mobile number + explicit consent. That's
Phase 0: small, safe, and it unblocks everything, with no external account or secret required yet.

## Decision

Two nullable-ish columns on the backend-owned `students` table, threaded through domain → adapter → service → API →
frontend, plus a validator and a dedicated write path:

- **Migration `0021`** (`0021_student_mobile_whatsapp.py`, down_revision `0020`; backend chain,
  `alembic_version_backend`): add `students.mobile_number` (`String`, **nullable**, NOT unique, no CHECK) +
  `students.whatsapp_opt_in` (`Boolean`, **NOT NULL, server_default false** — consent is never assumed; existing rows
  adopt false). Additive, fully reversible.
- **`domain/phones.py`** (new, pure — stdlib `re` + `domain.errors.ValidationError` only, layering-safe): a **loose**
  `validate_mobile(str | None) -> str | None` — `None`/blank → `None` (mobile is **optional** → stored NULL), else
  trim + `^\+?[0-9]{7,15}$` (an optional leading `+` then 7–15 digits — E.164-ish, NOT a per-country check; the
  provider validates authoritatively at send time), else `ValidationError`. Mirrors `domain/emails.py` in shape, with
  the added None passthrough. Applied at every write boundary so a stored number is always trimmed + shape-checked.
- **The read chokepoint** `_to_student()` (`adapters/repositories/postgres_students.py`) populates both fields on
  **every** read (get / list / list_page / list_by_ids / get_by_user_id / resolve_by_emails all route through it); the
  fresh-insert `create` path returns through the same mapper. The `Student` domain dataclass gains
  `mobile_number: str | None = None` + `whatsapp_opt_in: bool = False`.
- **Write paths:** `CreateStudentRequest` gains optional `mobile_number` + `whatsapp_opt_in` (default false); the bulk
  CSV import row gains an optional `mobile_number` (from a `mobile`/`phone` CSV column — **no opt-in for bulk**, since
  consent must be an affirmative act, not defaulted for an imported class); a **dedicated
  `PATCH /v1/students/{id}/mobile`** (`UpdateStudentMobileRequest {mobile_number, whatsapp_opt_in}`) — mirrors the
  existing `/status` route rather than folding into the class-only `PATCH /{id}` (which has a "empty body = 422"
  contract). `StudentService.set_mobile` resolves the student via a **school-scoped `get_student` BEFORE any write**
  (a foreign id → 404, never a cross-tenant write), validates/normalizes, writes via the new
  `StudentRepository.set_mobile`, and re-reads. `student:manage`, tenant from the token. **No admin-action audit** — a
  contact/consent edit is not a governance action (the `AdminAction` enum is deliberately NOT widened, consistent with
  class assignment).
- **`StudentResponse`** gains both fields (inherited by `StudentListItem`).

### Frontend

- `lib/api/types.ts` — `StudentResponse` gains `mobile_number: string | null` + `whatsapp_opt_in: boolean`.
- `lib/csv.ts` — `parseStudentCsv` header-detects an optional `mobile`/`phone` column (case-insensitive, trimmed;
  `mobile` wins if both present; empty cell → absent, not `""`). Fully back-compatible: absent header = today's
  name+email(+class) parse unchanged. Header detection stays gated on `name` **and** `email` present.
- `lib/api/endpoints.ts` — `createStudent`/`bulkImportStudents` thread the new fields; a new `updateStudentMobile`.
- **Student detail** (`students/[studentId]/page.tsx`) — a "WhatsApp" cell in the profile `dl` showing the number
  (`—` when unset) + an **"Opted in"/"Not opted in"** state as **text** (`StatusPill`, not colour-only) + a compact
  `MobileEditor` dialog (modeled on `ClassSelect`; a `tel` input + an opt-in checkbox; a client-side pre-flight regex
  identical to the backend, the server 400 surfacing as a toast; refreshes the SWR cache with the server response).
- **Create dialog** (`students/page.tsx`) — an optional "Mobile (WhatsApp)" input + an opt-in checkbox.
- **Bulk import** (`bulk-import-dialog.tsx`) — a Mobile preview column + help copy noting the optional `mobile`/`phone`
  column.
- Both opt-in checkboxes carry an `id` + `aria-describedby` pointing at a clarifying hint ("They'll receive their
  photos on WhatsApp once delivery is turned on.") so the control says what opting in *does* without over-promising
  (Phase 0 doesn't send). **List display:** deliberately **not** added — the detail page is the tasteful surface; a
  mobile column would be wide and low-value.

## Decisions made (with rationale)

1. **Dedicated `PATCH /{id}/mobile`**, not folded into the class-only `PATCH /{id}` — the latter's
   required-but-nullable `student_group_id` body would clash; the mobile+opt-in edit is one logical "WhatsApp contact"
   write, mirroring `/status`.
2. **`whatsapp_opt_in` settable at create** (default false); **bulk gets mobile only** — consent should never be
   defaulted-on for an imported roster.
3. **`validate_mobile` treats blank as NULL** (not an error) — mobile is optional; only a non-blank malformed value is
   a 400. Loose by design; the provider is the authoritative reachability check at send time.
4. **Detail-page display only** — no list column.
5. **No admin-action audit** on mobile edits — a contact/consent change is not a governance action.

## Verification

- **Backend gate:** ruff clean, mypy clean, layering clean (`domain/phones.py` imports only stdlib + domain errors),
  **pytest 730 passed / 49 skipped** at implementation (+ the two R2 tests → the touched suites re-run **70 passed**).
- **Migration `0021`** verified **up→down→up on a throwaway Postgres** (`wa_phase0_migtest`, dropped; the dev `app` DB
  confirmed untouched): columns present with correct types (nullable varchar / NOT NULL boolean default false),
  downgrade drops both, re-upgrade restores. A gated real-Postgres adapter round-trip
  (`test_student_mobile_and_whatsapp_round_trip`) ran on a second throwaway (`wa_phase0_gated`, dropped).
- **Tests added:** `test_phones.py` (validator truth table incl. the 7/15 boundaries, `+`+15-digits accept,
  separators/letters/`+`-only/too-short/too-long rejects, None/blank → None); service tests (create stores
  normalized mobile+opt-in; malformed → `ValidationError`; `set_mobile` set/clear + **opt-in an existing number
  without changing it** + **tenant-scoped 404-before-write** with a real cross-school student + missing → 404; bulk
  best-effort — a good mobile lands, a malformed row is `invalid` while a sibling still `created`); route round-trips
  (`PATCH /{id}/mobile` 200 / foreign 404 / malformed 400; create reflects mobile+opt-in); a gated adapter round-trip.
- **Frontend gate:** `npm run lint` + `npx tsc --noEmit` + `next build` clean; `/students` stays `○` static,
  `/students/[studentId]` is `ƒ` dynamic.
- **2× review loop:** **R1 (correctness/tenant/migration) — SHIP, 0 findings** (tenant 404-before-write proven with a
  real cross-school test, read-chokepoint completeness, migration/ORM mirror + linear chain, default consistency across
  DB/ORM/domain/schema/response, bulk best-effort isolation with matching tuple arity in every caller, layering purity,
  own-transaction adapter write, unambiguous route ordering). **R2 (edge/a11y/copy/back-compat) — SHIP, 3 should-fix +
  2 nits applied**: the `+`+15-digits accept test (locks "16 chars / 15 digits accepts"), the opt-in-only toggle test,
  the checkbox `id`/`aria-describedby` + clarifying hint on both forms, and disabling the mobile input while saving (to
  match the checkbox). CSV back-compat, field-length layering (schema `max_length=32` loose over the 16-char regex),
  and FE/BE regex parity all verified clean.

## Honest limits (documented)

- **Validation is loose** (`^\+?[0-9]{7,15}$`, no separators/spaces) — a UI is expected to send a compact number; the
  WhatsApp provider is the authoritative reachability check when a later phase sends. No per-country parsing.
- **Two independent states are storable** — a number without opt-in (intended: a contact can exist without consent)
  and opt-in without a number (defaults false, but toggleable). A future send path MUST gate on **both**
  `whatsapp_opt_in` AND `mobile_number is not None`; Phase 0 stores, it doesn't send.
- **No CSV opt-in column** — bulk imports store the number but never opt in; consent is set per-student via the detail
  editor or at create.
- **No uniqueness** on `mobile_number` — two students may share a guardian's number.

## What's next (not this phase)

- **W1** — the provider foundation: a `WhatsAppSender` port + a Gupshup/Wati adapter (+ a fake), a per-school
  `school_whatsapp_config` (non-secret channel/number + a new school-admin settings screen), the approved WhatsApp
  **media template**, and a ≤5 MB compressed image variant (reuse the BP17 Pillow thumbnailer). Needs a provider
  account + a WhatsApp Business number + one approved template — the owner sets these up when W1 starts.
- **W2** — the send flow: `POST /v1/students/{id}/whatsapp-send`, a `WhatsAppShareService`, an FE Send button reusing
  the BP13/BP30 select-mode, a throttled pool, a `whatsapp_send_log`, and a per-school budget cap.
- **W3 (later)** — send-to-all-in-an-event (needs a queue/worker), per-school numbers, delivery receipts.
