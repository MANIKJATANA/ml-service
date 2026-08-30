# 0090 — Product Build BP31: Onboarding feedback loop & copy/discoverability polish

- **Date:** 2026-08-30
- **Status:** implemented (FE gate green; 2× review→fix loop clean). **Committed + pushed.**
- **Phase:** **BP31** — the **final** phase of the Round-4 roadmap ([`product/09`](../product/09-improvement-roadmap-round-4.md)),
  a "floor-sweep 2" of small momentum + truthfulness fixes. Closes **R4-A01/A02/A08/A09/A14/A18** + **R4-F01/F02**
  (A11/A19/F05 dropped as already-shipped — see below). **FE-only — no backend change, no migration, no ML change, no
  new dependency, no new permission, no new env var.**

## Context

A grab-bag of individually-small onboarding/copy/discoverability gaps: the setup checklist didn't advance until the
60s poll (R4-A01), the reference-photo field didn't say it enrolls a face (R4-A08), the CSV import hid the server's
per-row reject reason (R4-A09), there was no live cue during matching (R4-A18), no inline fix action beside the
enrollment-failure note (R4-F01), the events-list "Matching" pill dead-ended (R4-F02), the edit-classes dialog had no
search (R4-A14), and the first-run dashboard was cold (R4-A02).

**Three items were CUT** — the plan-review verified they're already fully shipped, not "near-no-ops": **A19**
(clearable tags + the "choose the empty option to clear" explainer shipped in BP24a), **A11** (class grade/section
already displayed by BP11a), and **F05** (the partial-download messaging already distinguishes cancelled/capped/
partial). Implementing them would be churn/regression risk — cutting kept the final sweep crisp at **8 real items**.

**The one backend question answered:** A09's per-row reject `reason` is **already returned** — `BulkStudentResultResponse`
carries `status` + `error`, and the FE type `BulkStudentResult.error` exists; the students `BulkImportDialog` simply
didn't render it. So the whole phase is genuinely FE-only.

**Workflow (owner-directed multi-agent pipeline):** planning agent → plan-review agent (made the 3 cuts + the F02/F01
scope corrections) → implementation agent → 2× review loop.

## Decision — 8 FE-only items

- **A01 (checklist momentum)** — `void mutateDashboard()` / `void globalMutate("dashboard")` added **alongside** the
  existing mutates at the four completing flows (create-student, create-event, upload success, announce) so the
  `SetupChecklistCard` advances immediately on return (fire-and-forget — a slow dashboard refetch never blocks the
  primary toast). Plus an "Almost there — announce to reach your students." cue inside `SetupChecklistCard`
  (admin-only) when the next incomplete core step is announce (`nextKey === "has_distributed"` — the reachable
  near-complete moment; "all core done" is unreachable since the card retires once `has_distributed` flips).
- **A02 (dashboard warmth)** — warmed the first-run checklist heading ("Welcome — let's get your school set up") +
  subhead. Copy/visual only.
- **A08 (photo-field copy)** — both reference-photo dropzones now hint "This photo enrolls the student's face for
  matching — a clear, front-facing photo works best (up to 30 MB)." (a face-enrollment, not a profile pic).
- **A09 (import reject reason)** — `bulk-import-dialog.tsx` renders the per-row reason under the status pill: the
  server `error` when present (`invalid` rows), else a static fallback (`duplicate` → "Already has an account — may
  exist at another school." ; null-`error` → "Couldn't be created — try again."); nothing for `created` rows.
  Mirrors the staff bulk-invite pattern. **Backend already returned the field — pure FE render.**
- **A14 (edit-classes search)** — a `SearchInput` filters the `EditClassesDialog` checkbox list (by name/grade/
  section, case-insensitive); the `selected` Set + `onSave` are untouched, so a checked-but-filtered-out class still
  saves on PUT; a `role="status"` no-match line.
- **A18 (live-sync badge)** — a decorative "Matching…" pulse badge next to the Photos-card `StatusPill`, gated on
  `inFlight` (`processing_status ∈ {queued, processing}` — the same boolean driving `useEventStatus`'s poll), so it
  unmounts exactly when polling stops. `aria-hidden` (the existing "Matching since…" `aria-live` region is the
  authoritative announcement — no double SR chatter); the pulse respects the global reduced-motion guard.
- **F01 (inline fix beside the failure note)** — in the `enrollment_status === "failed"` branch, an inline action
  beside `EnrollmentFailureNote` (in the parent, where the handler + dialog live): `ml_unavailable` → the existing
  Re-enroll handler; `no_face`/`error`/null → the existing `ReferencePhotoDialog` (its label auto-flips Add/Replace on
  `hasPhoto`). Reuses the existing dialog/handler — the contextual fix right where the note explains the failure.
- **F02 (deep-link the Matching pill)** — the events-list "Matching" pill is wrapped in a `Link` to `/events/{id}`
  (the detail page's Process action) when the derived `pill ∈ {not_started, failed}` (there's actual work), with an
  `aria-label` mirroring the BP22 review-pill deep-link; a "Completed"/"Queued" pill is never wrapped. **The dashboard
  alerts can't deep-link to one event** — `needs_attention` carries no per-event IDs (a documented backend follow-up)
  — so the dashboard hrefs are unchanged; F02 closes the surface that *does* have per-event IDs.

## Correctness invariants (verified — R1 SHIP)

- **A01 fire-and-forget:** each dashboard revalidation is `void`-ed alongside (not replacing) the existing mutate; no
  double-fetch/revalidation loop (SWR dedups the shared `"dashboard"` key); the cue is admin-only and unreachable for
  a teacher. The R1 fix corrected the cue from a dead branch (`allCoreDone`, impossible while the card renders) to the
  reachable one-step-left state.
- **A14 selection-safe:** filtering changes only the rendered list; `onSave` PUTs the full `selected`, so a
  checked-but-hidden class survives.
- **A18 gates on `inFlight`** (not `pillStatus`, which can read "Completed" with a second batch pending).
- **F01/F02 branch correctly:** F01 on `enrollment_failure_reason`; F02 on the derived `pill`, href to Process (not
  the gallery). No nested-interactive-element issue.

## Files changed (8 — no new files, all FE)
`app/(school)/dashboard/page.tsx` · `app/(school)/students/page.tsx` · `app/(school)/students/[studentId]/page.tsx` ·
`app/(school)/events/page.tsx` · `app/(school)/events/[eventId]/page.tsx` · `app/(school)/events/[eventId]/upload/page.tsx` ·
`app/(school)/staff/page.tsx` · `components/students/bulk-import-dialog.tsx`.

## Verification

- **Frontend gate:** `npm run lint` (clean) + `npx tsc --noEmit` (clean) + `next build` (compiled, 20/20 static pages)
  all green; every touched page keeps its prerender marker (`/dashboard`, `/students`, `/staff`, `/events` stay `○`;
  the param routes stay `ƒ`). **No backend change → no backend suite delta.** No FE test harness (the repo norm) —
  verified by the gate + the manual-walk logic.
- **2× review→fix loop:**
  - **R1 (correctness): SHIP → 1 should-fix applied.** The A01 completion cue was a **dead branch** (`allCoreDone`
    requires `has_distributed`, which retires the card) — re-keyed to the reachable "only announce left"
    (`nextKey === "has_distributed"`) with copy "Almost there — announce to reach your students." Everything else
    verified clean (A01 fire-and-forget, A09 field names, A14 selection-safe, A18 `inFlight` gate, F01/F02 branches).
  - **R2 (edge/a11y/copy): SHIP → 1 should-fix + 2 NITs applied.** The A18 badge dropped `role="status"` (it
    double-announced with the existing "Matching since…" live region → made decorative `aria-hidden`); "Syncing…" →
    **"Matching…"** (BP21 one-grammar consistency); `students/page.tsx` unified `globalMutate("dashboard")` →
    the typed `mutateDashboard()` (+ removed the now-unused `swr` import). Left as-is: the A01 cue's `role="status"`
    (a genuine one-time progress moment, doesn't loop) and both F01 placements (the note-adjacent action is the right
    contextual home; the header buttons are the general controls). Confirmed clean: A09 fallbacks, A14 labelled
    search, F02 mirrors the BP22 pill link, A08/A02 copy.

## Honest limits (documented)

- **F02 is FE-only-bounded** — the dashboard "N photos to match" alert still can't deep-link to *that* event's Process
  button (the `needs_attention` payload carries counts, no per-event IDs); a true per-event dashboard deep-link is a
  small backend follow-up. F02 closes the events-list pill (which has the ID).
- **A01 momentum** — a photoless bulk-imported student stays `pending` (no successful enrollment), so it legitimately
  won't tick `has_enrolled_student`; the revalidation only advances a step the action actually completes.
- **A19/A11/F05 were dropped** as already-shipped/already-honest (BP24a/BP11a) — not implemented.
- **No FE automated tests** (the repo norm) — verified by the gate + manual walk.

## Next

**BP31 is complete — and with it the entire Round-4 roadmap (BP26 → BP27 → BP28 → A15 → BP29 → BP30 → BP31) is
done.** The v1-scoped, pre-release staff/admin improvement track ([`product/08`](../product/08-product-review-round-4-staff-admin.md)
/ [`product/09`](../product/09-improvement-roadmap-round-4.md)) is fully delivered. Remaining open work is the parked
backlog — **BP12** (outbound email/SMS distribution), **BP15** (accuracy at scale), **BP16** (lifecycle & retention),
the **BP6 video timeline**, and the **blocked** BP22 slice 4 (student "This isn't me" safety) — tracked in
[`product/05-parked-backlog.md`](../product/05-parked-backlog.md). A phase starts only on owner pick + scope
re-confirm.
