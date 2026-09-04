# 0102 — Event-photo fan-out: "send selected photos to whoever appears in them"

- **Date:** 2026-09-05
- **Status:** implemented (BE ruff+mypy+pytest+layering green; FE lint+tsc+build green; 2× review
  loop). **Not yet committed (pending the owner's go-ahead).**
- **Scope:** the owner-approved plan `event-all-photos-send-to-appearing-plan.html` — on the event
  gallery's **"All photos"** tab, select photos and **fan them out to the students who appear in
  them** (each student gets the subset they appear in), with a **pre-send preview** ("show once").
  **BE + FE; no migration, no ML change, no new dependency, no new permission** (reuses
  `whatsapp:send`).

## Context

W2 ([0094](0094-product-build-WhatsApp-W2-send-flow.md)) shipped a **student-centric** WhatsApp send
(one student → their photos) and **deliberately rejected photo-fanout** (one photo → everyone in it)
as "too risky." The owner now wants exactly that on the "All photos" tab, mitigated by a preview +
the existing consent/budget gates. This decision **revises 0094's student-centric-only stance**
(owner sign-off = this request; recorded here).

The "All photos" tab already had a BP13 multi-select (used for Download); this adds a "Send to
appearing students" action + a preview dialog over it.

## Decision

- **The recipient set is the BP5 EFFECTIVE overlay ∩ the selection** —
  `GalleryService.event_photo_recipients(school_id, event_id, media_ids)` reuses
  `effective_event_pairs` (the same rejected-excluded/added-included rule as every gallery read),
  intersects with the selected `media_ids`, and returns each appearing student paired with the
  subset they appear in (most-matched first). **The safety spine:** a `media_id` outside the
  event/school, or one no one effectively appears in, **contributes nothing** — so a crafted id can
  never leak a student or fan a send outside the event; a `rejected` pair is never a recipient.
- **The fan-out reuses the fully-gated per-student send** —
  `WhatsAppShareService.send_event_photos(...)` loops `send_student_photos` per recipient, so **every
  per-student gate is inherited unchanged** (consent [opt-in + number], the monthly budget [read
  from the DB per call → respected across the fan-out], the effective-set re-intersection, the
  interim divert, the send-log, PII-free). A **non-consenting** student is **skipped** (never
  aborting the fan-out); **interim mode** diverts every recipient's photos to the test number
  (consent bypassed, matching the per-student behaviour). WhatsApp being unconfigured is checked
  **once up front** → a clean 400 for the whole fan-out (rather than N per-student "skipped" rows).
- **Two endpoints on the events router** (`whatsapp:send`, tenant from the token):
  - `POST /v1/events/{id}/photo-recipients` — the **preview**: per-student `{name, photo_count,
    opted_in, has_number}`. Sends nothing.
  - `POST /v1/events/{id}/whatsapp-send-photos` — the **fan-out send** → an aggregate summary
    (`students_sent`/`students_skipped` + total `sent`/`failed`/`skipped`, PII-free). Both cap the
    body at 1000 media ids (→ 422) and require ≥1.
  New frozen VOs `EventPhotoSendStudentResult`/`EventPhotoSendSummary` (`domain/models.py`); schemas
  in `api/schemas/whatsapp.py`. No container wiring change (both services already built).
- **FE:** a "Send to appearing students" button in the "All photos" select bar (when ≥1 selected) →
  a **`SendToAppearingDialog`** that fetches the preview (SWR), shows the recipient list + "N
  students · X messages · M skipped", and — only on confirm — fires the send (honest toast:
  "Sent X photos to Y students · Z skipped"; a 400 "not configured" surfaces its message). On a
  successful send it exits select mode. The preview also carries an **`interim`** flag (platform
  test mode) → the dialog then shows a "Test mode — all N recipients go to the test number" note and
  lets the send proceed even with no opted-in student (the server diverts all to the test number).

## Verification

- **Backend gate:** ruff + mypy (284 files) + layering clean; **`test_event_photo_fanout.py` — 17
  tests** (recipients: groups-by-student ∩ selection / rejected-excluded + added-included /
  foreign-media-ignored / foreign-event-404; fan-out: sends-each-consenting-their-subset + PII /
  skips-non-consenting / unconfigured-400 / budget-across-students / interim-to-test-number /
  rejected-never-sent / **best-effort-on-per-student-error**; routes: preview 200 shape (+ `interim`)
  / send 200 PII-free / teacher-allowed + student·platform-403 / over-cap-422 / empty-422 /
  foreign-event-404). Full backend suite 850 passed (+ a pre-existing unrelated rate-limit
  full-suite flake — passes in isolation).
- **Frontend gate:** lint + tsc + `next build` green; the gallery route stays `ƒ`.
- **No migration, no ML change** — pure composition over existing tables/ports.
- **2× review loop:**
  - **R1 (security/correctness/entitlement) — 0 blockers.** The safety spine proven airtight: a
    crafted/foreign/rejected `media_id` contributes nothing (never a recipient, never fans a send
    outside the event); tenant token-derived everywhere; the per-student send re-gates a second time
    (defense in depth); budget respected sequentially (no double-spend); PII-free. Applied its 2
    should-fixes: **S1** — the per-recipient loop is now **best-effort** (wraps `send_student_photos`
    in `try/except (NotFoundError, ValidationError, UpstreamError)` → records the one student
    `reason="error"` + continues, so a concurrent delete/opt-out can't partial-abort the fan-out;
    tested); **S2** — the preview gained **`interim: bool`** (test mode) so the FE enables the send
    even with no opted-in student (the server diverts all to the test number) + shows a "Test mode"
    note, keeping the clear normal-mode "Send disabled when nothing sendable".
  - **R2 (edge/a11y/UX/copy/plan-fidelity) — 0 blockers.** Both R1 fixes verified correct (the
    best-effort catch set is exactly the surface `send_student_photos` raises — a programming error
    still propagates; the `interim` flag flows schema→route→FE, `canSend` correct for both modes,
    the warning banner AA-passing). Dialog a11y (`role="status"`/`role="alert"`, the scrollable
    recipient list, AA `text-ink-secondary`), the toast honesty, and plan fidelity all confirmed.
    Applied its should-fix (this doc's test count + the review-loop + the `interim` note) + a NIT
    honest-limit note (below).

## Honest limits (documented)

- **Photo-fanout reverses 0094** (owner-approved). Guarded by the preview + consent + budget + the
  effective overlay. New string implies in-app WhatsApp only (outbound reach stays parked BP12).
- **Cost:** the fan-out can send many messages (Σ per-student photo counts). The preview shows the
  total up front; the monthly budget caps it (over-budget photos are skipped, surfaced in the
  summary).
- **Per-student re-resolve:** reusing `send_student_photos` re-resolves each student's effective set
  (an extra read per recipient). Bounded at v1 scale; a batched send is the scale-up (safety > micro-
  perf — the reuse inherits every gate unchanged).
- **Selection is over the LOADED photos** (the "All photos" tab is server-paginated); there's no
  "select all across pages" yet (mirrors the existing download-select limit).
- **No server-side dedupe** across repeated fan-outs (a re-send re-sends — double cost); the Send
  button is in-flight-disabled.
- **Budget-skipped students aren't in the per-student tallies** — a consenting student whose photos
  are ALL over-budget-skipped shows in the aggregate `skipped` (and the sticky "info" toast) but not
  in `students_sent`/`students_skipped` (they neither sent nor were consent-skipped). Rare at the
  12k/mo cap; the aggregate counts stay honest.

## What's next

- Awaiting the owner's commit. Real (non-interim) delivery still needs the owner's live Meta/Gupshup
  setup (per the WhatsApp track).
