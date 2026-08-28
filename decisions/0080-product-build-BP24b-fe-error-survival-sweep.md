# 0080 — Product Build BP24b: Two-way doors (the FE error-survival sweep)

- **Date:** 2026-08-28
- **Status:** implemented (gate green; 2× review loop clean)
- **Phase:** **BP24b** — the FE half of **BP24 (Two-way doors)**, Round-3 review theme **P**
  ([0064](0064-product-review-round-3-ux.md), [`product/06`](../product/06-product-review-round-3-ux.md) §P,
  roadmap [`product/07`](../product/07-improvement-roadmap-round-3.md) BP24), redeeming R3-A2-11 + R3-S3-06 +
  R3-S3-01 + R3-A2-10/A3-10. The backend "doors" (clearable tags + classes-at-scale) were **BP24a**
  ([0079](0079-product-build-BP24a-clearable-tags-classes-at-scale.md)). **FE-only — no backend/ML change, no
  migration, no new dependency, no new permission.**

## Context

Theme P's "batch work survives errors" half — three FE gaps where a batch op failed silently or hid the
actionable state:
- **The CSV error loop was manual (R3-A2-11):** the import preview pre-flagged nothing, and results exported only
  *created* rows' credentials — fixing 30 typo'd emails meant hand-transcribing them into a new file.
- **Staff download-all could report success on a partial/empty archive (R3-S3-06):** it toasted "Downloaded N"
  without flagging `n < selected`, and an all-fetches-fail run looked like a user-cancel — the student page did
  the same op honestly.
- **The residue (R3-S3-01 + A2-10/A3-10):** create-teacher was the one create that never refreshed its roster;
  the notify roster was an unpaginated wall where "who hasn't opened?" had to be found by eye.

## Decision (all FE)

### Slice 2 · The CSV error loop (`components/students/bulk-import-dialog.tsx`)
- **Pre-flag in the preview:** a pure `flagRows()` marks each parsed row **Ready / Duplicate / Invalid** (a light
  email regex + **in-file case-insensitive** duplicate detection, first-occurrence-wins) — shown as a status pill
  in the preview table + a live "N of M ready … K flagged will be skipped" summary. The **server still validates
  authoritatively** (best-effort per row); this is a heads-up so problems are seen before submit, not discovered
  in the results.
- **"Download skipped rows"** on results: exports the non-`created` rows (duplicate/invalid/error) as a
  `name,email` CSV via a shared `saveCsv` helper (refactored from `downloadCredentials`) — fix-and-reimport with
  no transcription.

### Slice 4 · Honest partial downloads (`lib/hooks/use-download-all.ts` + both call sites)
- `useDownloadAll`'s result gains a **`cancelled`** flag: `streamToDisk` returns `{saved, cancelled}` — dismissing
  the save dialog → `cancelled: true` (distinct from `saved: 0` because every fetch failed); the buffered
  all-failed path still **throws** (→ the caller's catch).
- **Both** call sites unify on the honest branches: `cancelled` → silent (stay in select mode / no toast),
  `saved === 0 && !cancelled` → an **error** toast, `capped` → "the first N of M", `0 < saved < total` → "saved N
  of M", full → success (staff) / silent (student). So a mere cancel never reads as success, and an all-failed run
  is flagged instead of looking like a cancel.

### Slice 5 · The residue (`app/(school)/staff/page.tsx` + `events/[eventId]/page.tsx`)
- **Create-teacher refreshes its roster:** `CreateTeacherDialog` gains an `onCreated` prop wired to
  `useStaff().mutate()` (fired on success), so a new teacher appears without a reload (R3-S3-01).
- **Notify roster: a "Not opened" filter + collapse** (FE-only over the already-fetched, bounded roster): a
  reused `FilterChips` (All / Not opened, with counts) + a `ROSTER_PREVIEW=12` collapse ("Show all N / Show
  fewer") derived each render from `roster.students` — so "who needs a nudge?" is one click, not an eye-scan.

## Consequences / honest limits (documented)
- **The CSV pre-flag is a client heads-up, not the source of truth** — the server's per-row verdict is
  authoritative (a rare edge the regex misses still surfaces as `invalid`/`error` in the results, and "Download
  skipped rows" re-exports the **server's** non-created set).
- **The roster is still fetched whole** (the endpoint is unpaginated — the collapse/filter is FE-only over a
  bounded roster); true server pagination is the documented scale-up.
- The download honesty covers cancel / partial / capped / all-failed; the non-streaming **cap** (500) is the
  pre-existing BP9 limit (browsers without the File System Access API). One honest edge is preserved from that
  BP9 behavior: a **capped + partial** run (buffered >500, but some of the first 500 also failed) still reads
  "the first 500 of M" — the capped copy assumes the 500 saved. `saved === 0` is checked **before** `capped`, so
  an all-failed capped run correctly shows the error (never "saved the first 500"); only the mixed
  some-saved-some-failed capped case slightly over-claims, matching the pre-BP24 student path exactly.
- **FE-only** — no backend/ML change, no migration, no new dependency, no new permission.

## Verification
- **Frontend:** tsc + lint + `next build` green (no route static/dynamic change). No BE/ML suite delta.
- **Manual-walk items** (no FE test framework): the preview flags a duplicate + a typo'd email; "Download skipped
  rows" re-exports them; a partial staff download reads "saved N of M" (not a false success); a cancelled one
  stays silent in select mode; an all-failed one shows an error; a newly-added teacher appears immediately; the
  roster filters to "Not opened" and collapses past 12.
- **2× review loop** (both **SHIP, 0 blockers, 0 should-fix**):
  - **R1 (correctness / shared-hook blast radius / state safety)** — verified the shared `useDownloadAll` change
    is contained to exactly its **2** download call sites (both updated), all 3 `DownloadAllResult` return paths
    correct (streaming `{saved,capped,cancelled}` / buffered / early-return), the buffered all-failed path still
    **throws** (not swallowed as a cancel), both call sites `exitSelect()` only on a real save, the CSV pre-flag
    is pure + index-aligned, and the roster filter/collapse is derived each render (no duplicated state, a filter
    change resets the collapse, empty → "Everyone matched has opened"). **2 optional NITs, not applied** (a
    `flagRows` `useMemo` the React compiler already handles; the advisory-preview copy — both "no change
    required").
  - **R2 (a11y / copy / edges / honest-limits)** — verified the scoped `<th scope="col">` Status header, the
    text-labelled status pills (meaning not by color alone), `role="status"` on the preview summary + the
    "Everyone …" empty state + the toast live-region split (`status` for capped/partial, `alert` for all-failed),
    no focus loss on roster collapse (the toggle is a never-unmounted sibling), the all-invalid-file + 12-vs-13
    boundary + `saved === 0`-before-`capped` precedence edges, and the staff/student toast + flag-palette
    consistency. **3 NITs**: 2 no-change (roster empty-state wording only reachable under the `not_opened` filter
    where it's correct; the student all-failed two-phrasing across the streaming/buffered paths, both honest) +
    **1 doc-only applied** (the capped+partial copy edge, now in honest limits above).

## Next

**BP24 (Two-way doors) is complete (a + b)** — the recommended Round-3 tail (BP18 → … → BP24) is done. The
remaining open items are the parked set (**BP12/15/16**, the BP6 video timeline — `product/05`) and the earlier
**blocked** BP22 slice 4 (student "This isn't me" safety); a phase starts only on owner pick + scope re-confirm.
