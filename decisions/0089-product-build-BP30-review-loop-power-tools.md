# 0089 — Product Build BP30: Review-loop power tools at scale

- **Date:** 2026-08-30
- **Status:** implemented (FE gate green; 2× review→fix loop clean). **Committed + pushed.**
- **Phase:** **BP30** — a Tier-2 phase of the Round-4 roadmap ([`product/09`](../product/09-improvement-roadmap-round-4.md)),
  **the review lane's power tools at 200-ambiguous-match volume**. Closes **R4-A20/A21/A22/A23** + **R4-F04**.
  **FE-only — composes shipped BP13/BP22/BP5 primitives; no backend change, no migration, no ML change, no new
  dependency, no new permission, no new env var.**

## Context

The staff review lane (BP13 batch-review + BP22 review-armed) is correct but lacked power tools at scale: batch-undo
was undiscoverable and there was no way to re-see a rejected match for a spot-check (R4-A20); no confidence-threshold
*select* (R4-A21); the lane was grid-only with no per-tile context (R4-A22); the add-students search gave no
pagination feedback (R4-A23); and the lightbox dead-ended at the last loaded tile instead of auto-paging (R4-F04).

**Two load-bearing invariants (preserved, verified in code):**
- **No auto-confirm** (BP22's stance, decision 0076) — the threshold multi-select **stages** a selection; the human
  clicks Confirm/Reject to commit. Nothing auto-writes.
- **Staff-only / student-safety** — the "show removed/rejected" spot-check lives inside `AppearanceEditor`, which the
  student lightbox never renders (`showAppearances={false}`), reads only the already-staff-gated appearances endpoint
  (`gallery:view_all`), and leaves the BP5 `effective_*` gate (student reads + download mint) untouched.

**Workflow (owner-directed multi-agent pipeline):** planning agent → plan-review agent (made the Option-A call for the
show-rejected surface) → implementation agent → 2× review loop.

## Decision — 5 FE-only items

1. **Threshold multi-select (R4-A21)** — `NeedsReview` (`gallery/page.tsx`) gains a "Select below" row: preset chips
   (`< 60/70/80%`) + a free `%` field. `selectBelow(pct)` **replaces** `selected` with the pairs whose rounded
   confidence `< pct` — it calls **only `setSelected`, never `batchReview`** (the human commits via the existing
   Confirm/Reject buttons). The free field is clamped `Math.min(100, Math.max(0, n))` (a typed 500 can't
   over-select the whole lane); empty/NaN → no-op.
2. **Discoverable batch-undo (R4-A20, half 1)** — `NeedsReview.apply()` captures the resolved `ReviewPair[]` into a
   transient `lastRejected` **before** `setSelected(new Set())`/`await mutate()` (no stale closure) when the verdict is
   `rejected`, and renders an **inline banner** (`role="status"`, not a toast — it hosts an async button) "Rejected N
   matches · Undo". Undo fans out `Promise.allSettled(lastRejected.map(p => undoCorrection(p.mediaId, p.studentId)))`
   → `mutate()` + `globalMutate("dashboard")`, spinner while in-flight, then clears. `undoCorrection` reverts each
   pair to raw-ML `needs_review` pending (it reappears in the lane); `allSettled` makes a colleague-re-decided pair a
   harmless no-op. A confirm/new-reject batch replaces/clears the banner. **No batch-delete endpoint needed.**
3. **"Show removed (N)" disclosure (R4-A20, half 2 — Option A, FE-only)** — `AppearanceEditor` already receives
   `verdict:"rejected"` rows (staff-gated) and client-filtered them out; a **"Show removed (N)"** disclosure
   (`aria-expanded`) now re-lists them (`StudentRefAvatar` + struck-through name + confidence) each with a per-row
   **Re-add** (`aria-label`) → `undoCorrection` → `onChanged()`. `N` = `appearances.filter(verdict==="rejected").length`
   from the same prop (no new fetch); hidden when `N === 0`; additive/safe for both callers (lightbox +
   `photos/[mediaId]`). An event-wide rejected *grid* (Option B) would need a new read — **deferred**, documented.
4. **Table-view toggle (R4-A22)** — a `view: "grid" | "table"` local state (default grid) + a toggle (`aria-pressed`).
   The table renders the same `pairs` as denser rows (checkbox + `SignedImage` thumb + `StudentRefAvatar` + name +
   confidence% + "Open photo →"). Selection/Confirm/Reject/Reject-all/threshold/undo all act on the **same `selected`
   set** — purely presentational, local state only.
5. **Add-students popover cue (R4-A23)** — `AddStudents` destructures `total` from `useStudents` (already returned by
   `useInfiniteList`) and shows **"Showing first X — type to refine"** (X = the post-`present`-filter pickable count),
   only when more pages exist (`total > items.length`), suppressed while loading / no query. No "of Y" (Y counts
   present students too, reads oddly). No extra fetch.
6. **Lightbox auto-paging (R4-F04)** — `PhotoGrid` threads its existing `hasMore`/`loadingMore`/`onLoadMore` into
   `Lightbox`; `canNext = index < mediaIds.length-1 || (hasMore ?? false)`; a `goNext` (`useCallback`) at the last
   loaded index calls `onLoadMore()` **only if `!loadingMore`** (double-fetch gate) and sets a `wantNext` ref; a
   `useEffect` keyed on `[mediaIds.length, …]` advances `index` once the page lands then clears the ref (so `index`
   can never point past `mediaIds`). Both ArrowRight and the next button route through `goNext`. Callers that pass no
   paging props (`EventStudentPhotos`, the student `/me` gallery) behave exactly as before (props optional →
   `hasMore` false). The review-lane grid is a hand-rolled `<ul>` (not `PhotoGrid`), so item 5 doesn't touch it.

## Correctness / entitlement invariants (verified — R1 SHIP)

- **No-auto-confirm:** the threshold control calls only `setSelected`; `apply`→`batchReview` remains the sole write
  path, human-triggered.
- **Student-safety:** the show-removed disclosure is inside `AppearanceEditor`, gated by `canManageAppearances &&
  showAppearances`; the student `/me` lightbox passes `showAppearances={false}` → the editor (and the disclosure)
  never render; the BP5 `effective_*` gate + download mint are untouched. Nothing widens a student's view/download.
- **Undo async:** `lastRejected` captured pre-`mutate` (no stale read); `Promise.allSettled` idempotency-safe;
  `undoCorrection` is a tenant-checked delete (no-op if already gone).
- **Lightbox race-safe:** the `!loadingMore` gate + `wantNext` ref + length-keyed advance prevent a double page-fetch
  and an out-of-range `index`; the effect self-terminates (no re-render storm); hooks unconditional (Rules of Hooks).

## Files changed (4 — no new files, all FE)
`app/(school)/events/[eventId]/gallery/page.tsx` (items 1, 2a, 4-table) · `components/gallery/appearance-editor.tsx`
(items 2b, 5-cue) · `components/gallery/lightbox.tsx` (item 6) · `components/gallery/photo-grid.tsx` (item 6).

## Verification

- **Frontend gate:** `npm run lint` (0 errors/warnings) + `npx tsc --noEmit` (exit 0) + `next build` (compiled
  successfully) all clean; the gallery route stays dynamic (`ƒ`), no other route's prerender changed. **No backend
  change → no backend suite delta.** No FE test harness (the repo norm) — verified by the gate + the manual-walk
  logic.
- **2× review→fix loop:**
  - **R1 (correctness/entitlement): SHIP, 0 blockers.** Verified both invariants, the undo async correctness, and the
    lightbox auto-page race-safety (no double-fetch, no out-of-range index, self-terminating effect). 4 optional NITs.
  - **R2 (edge/a11y/copy): SHIP-READY, 0 blockers → 4 polish fixes applied:** the removed-row confidence % moved
    `text-ink-muted` → `text-ink-secondary` (data-bearing text → AA, the BP25 convention); the free-% field clamped to
    `[0,100]`; the `AppearanceEditor` docstring updated (the direct "Show removed" Re-add, not only "the dropdown");
    the popover cue's trailing period dropped (cross-surface consistency with the audit picker cue). A11y confirmed
    sound (chips/toggle/Apply are named `<button>`s, the undo banner is `role="status"`, the disclosure has
    `aria-expanded` + count, per-row Re-add `aria-label`). NIT left as-is: the table is a labelled dense row-list, not
    the `Table` primitive (reuse would be churn for no a11y win — a legitimate distinct pattern).

## Honest limits (documented)

- **Still no auto-confirm** — threshold-select stages; the human commits. BP30 doesn't change BP22's stance.
- **Per-event lane** — every power tool operates within one event's review tab; no cross-event bulk review.
- **The batch-undo window is session-transient** — the inline banner lives until the next batch / a `mutate` settle /
  leaving the tab; it's not a durable undo log.
- **"Show removed" is per-photo (Option A)**, not an event-wide rejected grid — staff spot-check where they open a
  photo; the event-wide grid (Option B, one small staff-gated read) is a documented follow-up.
- **The popover cue counts the first server page** ("type to refine"), not a full paginator — the popover still
  doesn't load further pages (unchanged from BP9).
- **The review-lane table isn't windowed** — it dumps all `pairs`, which is fine at the ~200-per-event lane size (the
  event-review read isn't paginated).

## Next

**BP30 (Review-loop power tools) is complete.** Next and **final** Round-4 phase: **BP31 (Onboarding feedback loop &
copy/discoverability polish)** — a batch of small independent FE fixes (return-to-checklist momentum, deep-linked
dashboard alerts, inline "Replace photo" in the failure note, surfacing the import server-reject `reason`, a live-sync
badge during matching, reference-photo/category/clear-tag copy, display cleanups; closes R4-A01/02/08/09/11/14/18/19,
F01/F02/F05). Through the full Plan → plan-review → implement → 2× review pipeline, committed + pushed on completion
(autonomous).
