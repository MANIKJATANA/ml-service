# 0036 — Frontend student self-view (Phase F6)

**Date:** 2026-07-13
**Status:** Accepted

## Context

F5 ([0035](0035-frontend-galleries-and-download.md)) delivered the **staff** distribution UX. F6 is
the **recipient's** side: a logged-in student sees exactly the photos they appear in and downloads
them. It reuses the F5 gallery components almost wholesale. **No backend change** — the `/me`
endpoints ([0028](0028-galleries-and-download.md)) already exist and **reuse the F5 gallery schemas**.

## Decisions

### 1. One consolidated page (`(student)/me/events` = "My Photos")

The plan's separate `me/events` + `me/gallery` are **consolidated into one filtered page** — the
student's single nav item. `useMyEvents()` drives a `FilterChips` selector (**"All events"** +
per-event, shown only when the student is in >1 event); the selection drives `useMyMedia(eventId | null)`
→ `PhotoGrid`. Two routes would have meant a redundant event index or duplicated grid plumbing; the
chips-as-filter mirrors the staff by-student view. (`"" `= all; `selected || null` maps the sentinel to
the unfiltered fetch.)

### 2. Appearances hidden for students — a real capability boundary

`GET /media/{id}/appearances` is `gallery:view_all` (**staff-only** — a student gets 403) **and** it
would leak other students' names. The reused Lightbox gained a **`showAppearances`** prop (default
`true`; `PhotoGrid` threads it through). The student page passes `false`, which **gates the fetch**
(`useMediaAppearances(null)` → no request) *and* hides the "In this photo" panel — defense-in-depth on
top of the backend RBAC. Verified in review: no student code path reaches any `gallery:view_all`
endpoint (the page imports only `useMyEvents`/`useMyMedia`; the `(student)` group has no gallery/photo
route).

### 3. Reuse, not a separate viewer

`showAppearances` is one boolean, defaulting to staff behaviour so the three existing staff call sites
are unchanged. A dedicated `StudentLightbox` would duplicate ~90 lines of Dialog/focus/nav for one
hidden block. The student Lightbox panel is sparser (counter + close + **Download**) but still carries
three real controls — an acceptable v1, not empty chrome. Its F5 a11y is intact (the `aria-live`
counter, focus-trap, arrow/Esc nav all sit outside the `showAppearances` conditional).

### 4. Download works for students (entitlement-scoped)

Tiles + the Lightbox download hit `GET /media/{id}/download`, which is entitlement-gated (a student may
fetch only media they appear in). The `/me/media` roster is always entitled, so the normal path works;
a hypothetical 404 degrades gracefully (`SignedImage` fallback + the download button `disabled` while
`download` is undefined).

### 5. Role isolation + data layer

The `(student)` layout is `AuthGuard allow={["student"]}`; role routing lives in the per-group guards
(`proxy.ts` is unchanged — a cookie-presence gate only). No new types (reuses `EventForStudentResponse`
+ `GalleryMediaResponse`); new endpoints `myEvents`/`myMedia`; hooks `useMyEvents`/`useMyMedia` in
`lib/hooks/use-my-gallery.ts` (self-scoped `me/*` SWR keys, distinct from the staff keys).

## Alternatives rejected

- **A separate `me/gallery` route** — consolidated into the one filtered page (§1).
- **A dedicated `StudentLightbox`** — the `showAppearances` prop is the minimal, correct seam (§3).
- **A student `photos/[mediaId]` deep-link page** — deferred: low value (a shareable per-photo URL for
  a student), and it'd need its own appearances-suppressed variant. Students reach photos via the
  grid→Lightbox only.

## What this phase does NOT do (deferred, documented)

- **Live smoke not run** — Docker is down; the whole student read path is unverified: `/me/events` +
  `/me/media`, the entitlement-scoped signed download, and the image render. Needs a student account
  with processed appearances.
- **A11y sweep (F7):** loading/error state swaps (skeleton→content, →error) are **not announced**
  (`aria-live`/`aria-busy`) — a **systemic** gap shared by *every* list page since F2, so it belongs in
  F7's planned a11y sweep, not a one-off patch here. Likewise the `FilterChips` radiogroup has no
  arrow-key roving (each chip is a Tab stop; deferred since [0035](0035-frontend-galleries-and-download.md)).
- No student deep-link photo page (above); the sole event's name isn't surfaced on the single-event
  view ("My Photos" is acceptable framing).

## Testing

- Gate green (`eslint` + `tsc --noEmit` + `next build`, Node 22) after each review round. No backend
  change.
- **2× review→fix loop.** R1 (correctness + security) — **no blockers, no should-fix**; the two
  security-critical items were rigorously traced: **appearances isolation** (a student's grid/Lightbox
  fires no `gallery:view_all` request; panel fully hidden) and **download entitlement** (own-media only;
  graceful 404) are both correct and defense-in-depth. Wired `mutate` into `useMyMedia` for a sub-view
  Retry. R2 (design/a11y/edge) — **no blockers**; confirmed the consolidation + `showAppearances` are
  the right minimal calls and the sparse student Lightbox is acceptable; fixed the shared chip-count
  contrast to AA and the empty-view copy; deferred the systemic `aria-live` gap to F7.
- Live smoke **pending** the stack (above).

## Files

- **New:** `app/(student)/me/events/page.tsx` (was the F1 ComingSoon placeholder);
  `lib/hooks/use-my-gallery.ts`.
- **Changed:** `lib/api/endpoints.ts` (`myEvents`/`myMedia`); `components/gallery/lightbox.tsx` +
  `photo-grid.tsx` (additive `showAppearances`); `components/gallery/filter-chips.tsx` (chip-count AA
  contrast). **No migration, no backend change, no new dep.**
