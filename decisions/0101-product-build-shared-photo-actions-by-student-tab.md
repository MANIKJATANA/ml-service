# 0101 — Shared `StudentPhotoActions`: select/random send on the event "By student" tab

- **Date:** 2026-09-04
- **Status:** implemented (FE lint + tsc + `next build` green; 2× review loop). **Not yet committed
  (pending the owner's go-ahead).**
- **Scope:** the "easy follow-on" flagged in [0100](0100-product-build-student-appears-in-filter-and-select-send.md)
  — bring the student select/random Send/Download UX to the **event-gallery "By student" tab**, by
  **extracting a shared component** so both surfaces share one implementation (DRY). Plan:
  `event-by-student-select-send-plan.html` (owner-approved). **FE-only — no backend/ML change, no
  migration, no new dependency, no new permission.**

## Context

[0100](0100-product-build-student-appears-in-filter-and-select-send.md) added a per-photo **Select
mode** (Select all / Select random N / manual → Send K / Download K) to the student-detail "Appears
in" section, with the logic inline. The event-gallery **"By student" tab** (`EventStudentPhotos`)
only had "Send all / Download all" for the picked student's photos in that event. The owner asked to
apply the same treatment there. Since the tab is already scoped to one event + one student, only the
select/send/download division is needed (no event filter).

## Decision

- **Extract `StudentPhotoActions`** (`components/gallery/student-photo-actions.tsx`) — the select
  toggle + toolbar (Select all / Select random N / Clear / "N selected") + the browse/select
  `PhotoGrid` + the **Send + Download that target the selection (select mode) or the whole `media`
  (browse)**. It owns `selectMode`/`selected`/`randomN`, reuses `SendPhotosButton` (the same
  server-side effective-set intersection — **no entitlement change**) + an internal
  `PhotoDownloadButton` (the same streaming `useDownloadAll`). Props: `media`, student info,
  `resetKey` (clears the selection on a view/student switch — stale-safe), `zipEntryFor` + `zipName`
  (the caller owns the zip naming), optional `captionOf`, `canManageAppearances`, `leftHeader`
  (context node, e.g. a photo count), and `size` ("sm" for a compact tab, else md).
- **`AppearsInSection` (student detail)** now keeps only the event filter (All + latest chips +
  `EventPicker`, derived `activePicked`) and delegates the rest to `StudentPhotoActions`
  (`captionOf` = per-event captions in the "All" view, event-foldered `zipEntryFor`). The inline
  `pickRandomIds`/`PhotoDownloadButton`/select logic was removed (moved to the shared file).
- **`EventStudentPhotos` (By student tab)** now delegates to `StudentPhotoActions` (`resetKey =
  studentId`, `size="sm"`, a flat event-date `zipEntryFor`, `leftHeader` = the photo count) — so it
  **gains** Select all / Select random N / manual → Send K / Download K. Its old inline "Send all /
  Download all" was removed.
- **Consistency:** the sibling "All photos" tab's select verbs were aligned to the shared wording —
  "Select" → "Select photos", "Cancel" → "Done" (the repo's dialog convention) — so the gallery
  page's two select surfaces read the same.
- **By-student student filter (added):** at scale a big event's matched roster is a wall of chips.
  `ByStudent` now shows the **top `QUICK_STUDENTS` (4)** matched students (by `media_count`) as quick
  chips + a searchable **`StudentChipPicker`** (`components/gallery/student-chip-picker.tsx`) for the
  rest — modelled on `EventPicker` (client-side filter over the already-loaded `useEventStudents`
  roster, **no API call, no new dependency**). A picked non-quick student is surfaced as an extra
  active chip; the default selection is the **most-matched** student; the active pick is **derived**
  (stale-safe, like the event filter). This mirrors the student-page "Appears in" event filter,
  applied to students. FE-only, downstream `StudentPhotoActions` + entitlement untouched.

## Verification

- **Frontend gate:** lint + tsc + `next build` green (0 warnings after removing the now-unused
  `Download`/`SendPhotosButton` imports from the gallery page); routes unchanged.
- **Entitlement (no regression):** Send still routes through `SendPhotosButton` → the server, which
  intersects `media_ids` with the effective set; Download reuses the same entitlement-gated mint.
  Both surfaces pass only the picked student's own effective `media`.
- **2× review loop:**
  - **R1 (correctness/hooks/regression/entitlement) — 0 blockers.** The extraction is
    behavior-preserving on the student-detail; the By-student tab correctly gains the UX; hooks
    unconditional; `resetKey` reset can't loop; selection survives `PhotoGrid` windowing (a full
    `Set`); the download `entryBase` indexes `targetMedia` correctly; no entitlement widening.
    Applied its 2 NITs (dropped the unused `export` on `pickRandomIds`; commented the `leftHeader`
    placeholder).
  - **R2 (edge/a11y/UX/consistency/plan-fidelity) — 0 blockers.** Plan match confirmed. Applied its
    2 should-fixes: the **"Select photos"/"Done" verb alignment** on the "All photos" tab, and the
    **`size` prop** so the By-student tab keeps its compact (`sm`) Send/Download rather than stepping
    up to md. Documented the one behavior difference (below).

## Honest limits / notes (documented)

- **Behavior difference (student-detail):** because `StudentPhotoActions` (which owns `selectMode`)
  is unmounted during an **uncached**-event load gap, entering Select mode then switching to a fresh
  event resets to browse (a cached switch keeps the mode and just clears the selection via
  `resetKey`). The old inline version kept the mode across every switch. Acceptable — the selection
  had to be rebuilt for the new view anyway, and the **selection-safety invariant holds** (a
  selection can never act on another view's photos). Commented at the caller.
- Scope is the **student-detail "Appears in"** + the **event "By student"** tab. The event **"All
  photos"** tab (multi-student, photo-centric) is a separate, larger idea (a future
  send-to-appearing-students plan) — out of scope here.
- Random select is client-side over the loaded view; the BP9 500-photo non-streaming download cap
  still applies (honest capped toast) — both inherited from the reused `useDownloadAll`.

## What's next

- Awaiting the owner's review + commit. A separate, owner-flagged idea — the event **"All photos"**
  tab gaining a "send selected photos to whoever appears in them" fan-out (with a pre-send preview)
  — is planned separately (it reintroduces the photo-fanout that [0094](0094-product-build-WhatsApp-W2-send-flow.md)
  deferred, so it needs its own decision + sign-off).
