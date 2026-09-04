# 0100 — Student "Appears in": smart event filter + select/random send (plan Phases 2 & 3)

- **Date:** 2026-09-04
- **Status:** implemented (FE lint + tsc + `next build` green; 2× review loop). **Not yet committed
  (pending the owner's go-ahead).**
- **Scope:** Phases 2 & 3 of the owner-approved plan `student-photos-and-whatsapp-plan.html` (Phase 1
  = the platform-only WhatsApp move, [0099](0099-product-build-WhatsApp-platform-only-config.md)).
  Both are on the **student detail "Appears in"** section. **FE-only — no backend/ML change, no
  migration, no new dependency, no new permission, no new env var.**

## Context

The student detail "Appears in" section showed **one raw chip per event** and both **Send on
WhatsApp** + **Download all** acted on the student's *entire* effective set across all events. At
real scale (10–20+ events) the chip wall is unusable, and staff wanted to send/download **exactly
the photos they choose** (e.g. all of one event, or a random sample) rather than everything.

The send endpoint already accepts a `media_ids` subset (`null` = all, an array = only those,
server-intersected with the effective set), so this is **entirely frontend** — no send-API change.

## Decision

Revamp `AppearsInSection` (`frontend/app/(school)/students/[studentId]/page.tsx`) + add a new
`frontend/components/gallery/event-picker.tsx`.

### Phase 2 — smart event filter
- The filter row becomes **`All`** + the **latest `QUICK_EVENTS` (3) event chips** (newest-first by
  `event_date`, undated last) + a searchable **`EventPicker`** popover, shown only when there are
  more events than the quick chips (`hasMoreEvents`). `EventPicker` is modelled on BP10's
  `StudentPicker` but filters the already-loaded events list **client-side** (a student appears in a
  bounded number of events); it adds `aria-current` and a subtle active-trigger cue.
- **`All` (`picked === null`, the default)** shows the whole effective set (`useAllStudentMedia`),
  each photo captioned **"{event} · {date}"** (via the timezone-safe `formatEventDate`); a picked
  event shows just that event's photos (`useStudentMedia(studentId, activePicked)`).
- **Stale-safe:** the active view is **derived** — `activePicked = (picked in events) ? picked :
  null` — so a background revalidation that drops the picked event falls back to `All` and never
  strands the section or fetches a gone event (the "derived, not effect-reconciled" pattern the
  BP11a/b class/category filters use). A picker-picked non-quick event is always surfaced as a chip
  so `FilterChips.activeId` matches.

### Phase 3 — divide the send: select-all / random / manual
- A **"Select photos"** toggle enters SELECT mode: the `PhotoGrid` uses the shipped BP13
  `selectionMode`/`selectedIds`/`onToggleSelect` (a tile toggles instead of opening the lightbox),
  and a toolbar offers **"Select all (N)"** (the whole current view), **"Select random"** + a number
  input (`randomN`, default `DEFAULT_RANDOM = 10`; a client-side Fisher–Yates `pickRandomIds`,
  clamped to the view count), and **"Clear"**, with a `role="status"` **"N selected"** count. "Done"
  exits.
- The **Send + Download actions target `targetMedia`** = the **selection** in SELECT mode, or the
  **whole current view** in browse mode. Send reuses the existing `SendPhotosButton`
  (`mediaIds={targetIds}` → its confirm + the server-side effective-set intersection, unchanged);
  Download reuses a new **`PhotoDownloadButton`** — the old `StudentDownloadAll` extracted to act on
  a passed `mediaList` (same streaming `useDownloadAll` + entitlement-gated per-photo mint + zip
  foldering, no lost behavior). The selection **clears on any view change** (adjust-state-during-
  render) so a send/download can never act on another view's photos.
- **Behaviour parity:** browse mode on `All` still targets the whole effective set (== the old "send
  all"); picking an event scopes Send/Download to that event (the deliberate "select all of the
  current event" the owner asked for). The section stays **hidden until the student is matched into
  ≥1 photo**.

## Verification

- **Frontend gate:** lint + tsc + `next build` green; `/students/[studentId]` stays `ƒ` (dynamic).
- **Entitlement (no regression):** the WhatsApp send still routes through the server, which
  **intersects** the client `media_ids` with `GalleryService.student_media` (the BP5 effective
  overlay) — a crafted/non-effective id is server-`skipped "not entitled"`. Download reuses the same
  entitlement-gated mint. R1 verified no client path widens entitlement.
- **2× review loop:**
  - **R1 (correctness/hooks/async/entitlement) — 0 blockers, 0 should-fix.** Verified: all hooks run
    before the early returns; selection survives `PhotoGrid` windowing (a full `Set`, so "Select
    all" of a 200-photo view targets 200, not the mounted 48); the view-change reset can't loop; the
    server-authoritative entitlement intersection holds. Applied its NIT #1 → the **derived
    `activePicked`** stale-safe guard.
  - **R2 (edge/a11y/UX/copy/plan-fidelity) — 0 blockers.** Plan match confirmed for both phases.
    Applied its 2 should-fix: an **active-state cue on the `EventPicker` trigger** (it holds a
    persistent selection, unlike `StudentPicker`), and an **honest `randomN` input** (its displayed
    value is clamped to the current view's count while the state preserves intent for a bigger view;
    `pickRandomIds` already clamped). a11y confirmed: labelled number input, `role="status"` count,
    `aria-pressed` tile toggles (from `PhotoTile`), AA `text-ink-secondary` data text.

## Honest limits (documented)

- **Scope is the student-detail "Appears in" only.** The event-gallery "By student" tab could get the
  same select/random treatment later (an easy follow-on; deliberately out of scope to stay focused).
- **Random select is client-side** over the loaded view (the student-scale galleries load whole);
  the BP9 500-photo download cap on non-streaming browsers still applies (honest capped toast).
- In SELECT mode with nothing selected, Send/Download show a disabled "0" state (honest; the "N
  selected" count is right above).
- `randomN` state preserves the user's intent across views; the input's *displayed* value is clamped
  to the current view so it's never larger than what a "Select random" would actually pick.

## What's next

- The plan's 3 phases are complete (Phase 1 = [0099], Phases 2–3 = this). Awaiting the owner's review
  + commit. A future follow-on could extend select/random to the event-gallery "By student" tab.
