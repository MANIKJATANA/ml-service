# 0075 — Product Build BP20: The arrival moment (+ BP20b student chrome)

- **Date:** 2026-08-16
- **Status:** implemented (gate green; 2× review loop clean)
- **Phase:** **BP20 (The arrival moment)** — Round-3 review theme **L**
  ([0064](0064-product-review-round-3-ux.md), [`product/06`](../product/06-product-review-round-3-ux.md)),
  redeeming R3-A4-02/03/05/07 + R3-S3-11, plus the owner-approved companion **BP20b** (R3-S2-05, the student
  chrome). **One phase. FE-only — no backend/ML change, no migration, no new dependency, no new permission.**

## Context

The student receive surface had Pinterest-grade *mechanics* (BP3/BP9/BP17) but not the *moment*: BP4's flagship
"new photos" signal existed and then pointed at nothing. A "3 new" badge opened the grid on **three-year-old**
photos (oldest-first stream, the new event the *last* chip), the banner named no event and linked nowhere, every
unseen flag was **burned on page load** before anything was seen, the badge **froze** once-per-session, ~60 events
rendered as a **flat pill wall**, photos carried **no event/date**, and "Download all" produced `photo-001…900` in
one pile that **silently truncated to the oldest 500** on non-Chromium browsers. On top, the student wore the
admin's cool-gray sidebar chrome. Two Explore passes confirmed the whole theme is **display-only** — the backend
already serves everything (events/media oldest-first with no sort param → newest-first is a clean FE reverse;
`notifications.events` carries name/`event_date`/`unseen`; each media row carries `event_id`; `text-display-xl` was
a defined-but-unused token).

Owner calls: **full scope** (moment-fix + the BP20b warm reskin), **arrive-to-clear** mark-seen (deferred to
render, not on mount), **one phase**.

## Decision

All seven pieces are `frontend/`-only:

1. **Newest-first ordering.** `me/events/page.tsx` FE-`reverse()`s the events (chips + the event lookup) and the
   media (in `PhotoArea`) — the backend serves oldest-first and the media payload has no timestamp, so reversing
   the fetch order = newest-uploaded first. The Lightbox index + the download `entryBase(i)` index the same
   reversed array.
2. **Actionable banner + arrive-to-clear.** The banner lists this-visit's unseen events (a one-shot `newEvents`
   snapshot) as **filter buttons** (`setSelected(event_id)`); mark-seen moved **off mount** to fire once, after
   BOTH `notifications` loaded AND the first photo load **succeeded** (`PhotoArea` `onLoaded` → `photosLoaded`).
3. **Un-freeze the signals.** `useMyNotifications` + `useDashboard` opt into `{ revalidateOnFocus: true,
   refreshInterval: 60_000 }` (per-hook, not the global no-poll default) so a kept-open tab lights up.
4. **Grouped event filter.** New `EventFilter`: ≤ 8 events → the existing `FilterChips` (newest-first); beyond that
   → a year-grouped native `<select>` (`groupByYear`, undated → a trailing "Other" optgroup) — compact, accessible,
   never a phone-filling pill wall.
5. **Photo story.** `GalleryItem` gains optional `caption` ("{event} · {date}", built via an `eventMeta` map +
   `formatEventDate`); `PhotoGrid` threads `mediaCaptions[]` → `Lightbox` (a story line + folded into `alt`), and
   `caption` → `PhotoTile` (the tile's accessible name + a masonry hover scrim). Optional/back-compat — staff
   surfaces pass no caption and are unchanged.
6. **Named saves.** `useDownloadAll(mediaIds, { entryBase, zipName })` names zip entries **`{event}/{date}-{nnn}`**
   + the zip **`my-photos-{date}.zip`**; `useDownloadToDisk(…, label?)` names single saves by event; `onDownloadAll`
   returns `{saved, capped}`; the non-Chromium 500-cap surfaces an **honest sticky** toast; `toast(…, { sticky })`
   + `sanitizeFilename` (`lib/utils.ts`) added. Back-compat: no options → the legacy `photo-{nnn}` / `my-photos.zip`
   (staff callers unchanged).
7. **BP20b student chrome.** `AppShell` branches on `user.role === "student"` to a **warm slim** layout — a top bar
   (brand + a menu button opening the account drawer, reusing `NavList`/`UserFooter`) over a **`bg-canvas-warm`**
   wash (new `@theme` token), with a **`display-xl`** hero on My Photos. Staff/platform chrome is untouched; the
   resize-close effect is guarded off for students (their drawer is used at all sizes).

## Why

- **Reverse, not a backend sort.** The lists are fetched whole (bounded by the student's own matches) and windowed
  in render, so a FE reverse is exact and keeps the phase FE-only (no `desc` param, no paginated-path risk).
- **Arrive-to-clear on *successful* render.** Marking seen only after photos actually render (not on mount) is the
  owner's "simpler" choice AND correct — a load error must not dismiss unseen photos.
- **Per-hook polling.** Only the two badge keys opt back into revalidation; the rest of the app keeps the BP32
  no-poll defaults, and SWR dedupes the shared keys so the nav badge + page make one request per interval.
- **Story from data already on the page.** The media→event join is in-memory, so captions + saved-file names cost
  no new fetch.

## Consequences / honest limits (documented)

- **FE-only; no backend/ML/migration/dependency/permission change.** `git status` shows only `frontend/` (14 files
  + the new `event-filter.tsx`).
- **Mark-seen fires on a *successful* render only** — a media load error leaves the "new" flag set (unseen photos
  aren't wrongly dismissed); it clears on the next visit that renders, or when the in-page Retry succeeds.
- **The banner is a one-visit snapshot** — captured once from the first `notifications` payload. A *new*
  announcement arriving mid-session (via the 60 s poll) lights the **nav badge** but not this banner until the next
  page load. Capped at 6 chips + "+N more" so a long absence doesn't bury the photos.
- **Newest-first is a fetch-order reverse, not a true `created_at` sort** (the payload carries no per-photo
  timestamp) — it silently follows the backend's order if that ever changes.
- **Non-streaming 500-cap:** Safari / Firefox / iOS (no File System Access API) buffer-and-cap at 500; the honest
  sticky toast leads with the universal remedy (filter by an event) and names **desktop Chrome/Edge** (iOS Chrome is
  WebKit, same cap). A partial download's retry re-fetches everything (no failed-subset retry).
- **Per-event zip folders** in the "all events" download are deliberate (story-grouped, not a flat pile).
- **The warm wash is student-only + light-only** (`bg-canvas-warm` in the student shell branch; the app is
  light-only — a future dark theme would add the token).
- Verified: FE **lint + tsc + `next build` green**; no BE/ML suite delta. **2× review loop — no blockers.** **R1**
  (correctness/races) traced the reverse/index alignment across items/ids/captions/`entryBase` (incl. the buffered
  `slice` alignment), the arrive-to-clear one-shots (no double-mark / no loop), the per-hook poll + the BP21b 401
  interceptor interaction, staff back-compat on every touched caller, `sanitizeFilename` (no accidental char-range),
  the lazy-`Date` initializer, and the BP20b branch — **zero blockers**, one should-fix (the mark-seen-on-error
  asymmetry → made a deliberate, commented choice). **R2** (a11y/copy/consistency/edges) — no blockers → applied
  **3 fixes**: the banner is now a labelled `role="group"` (not an aria-live region wrapping buttons) with
  self-describing per-button names + a 6-chip cap; the capped-toast guidance leads with the universal remedy +
  names desktop Chrome/Edge (not "Chrome", which fails on iOS); the masonry scrim caption is `aria-hidden` (the
  accessible name is on the button) — plus softer partial-download copy; confirmed AA on the warm wash (ink 16.98:1,
  ink-secondary 5.58:1, accent-dark 10.82:1), the grouped-select label association, and null-date / long-name /
  video edge cases.
- **Next:** the owner picks the next Round-3 phase — the recommended order continues **BP22** (review loop, armed)
  → BP25/BP23/BP24 ([`product/07`](../product/07-improvement-roadmap-round-3.md)); a phase starts only on owner
  pick + scope re-confirm.
