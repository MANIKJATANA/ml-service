# 0035 — Frontend galleries + download (Phase F5)

**Date:** 2026-07-13
**Status:** Accepted

## Context

F4 ([0034](0034-frontend-events-and-processing.md)) delivered events + upload + processing.
**F5 is the distribution UX** — the payoff of the whole pipeline: staff browse an event's photos,
see who appears in each, and download them. It brings the **PhotoGrid** (masonry) + **Lightbox** and
reads the Phase-6 gallery contract ([0028](0028-galleries-and-download.md)). **No backend change** —
the gallery reads + the entitlement-gated download endpoint already exist.

## Decisions

### 1. Screens (`(school)` group — `gallery:view_all`, held by school_admin + teacher)

- **`(school)/events/[eventId]/gallery`** — Radix **Tabs**: *All photos* (browse-all
  `GET /events/{id}/media` → PhotoGrid) and *By student* (`GET /events/{id}/students` → a
  `FilterChips` selector → that student's photos in the event). A **"View gallery"** link was added
  to the event detail header (shown once `status.total > 0`).
- **`(school)/students/[studentId]`** — an **"Appears in"** section (`GET /students/{id}/events` →
  chips → their photos per event), hidden until the student is matched into ≥1 photo.
- **`(school)/photos/[mediaId]`** — a deep-linkable photo page: the image + appearances + download,
  with a breadcrumb back to the event gallery.

### 2. Lazy masonry (`PhotoGrid` + `PhotoTile` + `SignedImage` + `useInView`)

CSS-columns masonry (2/3/4 responsive, **8px gutter** per pinterest.DESIGN.md — imagery effectively
touches) with `break-inside-avoid`. Each tile defers its work until near the viewport via
`useInView` (a fire-once `IntersectionObserver`), then loads via a shared **`SignedImage`**: fetch the
signed URL → render → **one-shot re-mint on a 403** (expired URL) → a terminal `ImageOff` fallback if
the fetch OR the decode fails (nothing sits on a perpetual spinner). Tiles show **full-res images
scaled down** — there is no thumbnail endpoint in v1, which makes the lazy gate load-bearing for
bandwidth. Hover escalates the border (never dims the photo).

### 3. Lightbox (`components/gallery/lightbox.tsx`)

Full-screen Radix Dialog (`bg-ink/80` theater scrim): the image + **←/→/Esc** navigation, prev/next
buttons (bounds-guarded), a download button, and the appearances panel (side on desktop, bottom on
mobile). a11y from the review: the counter is an **`aria-live` region** (nav is announced), the image
`alt` conveys position, **initial focus is deterministic** (`onOpenAutoFocus` → the content, not the
conditionally-present arrow), and the image is a **keyed `SignedImage`** so retry state resets on nav.

### 4. Download (`GET /media/{id}/download` → `useDownloadToDisk`)

Gallery list items carry **no URL** — bytes are fetched lazily per tile via a short-lived signed URL,
avoiding N signing round-trips to render a list. `downloadToDisk` fetches the blob and clicks an object
URL to force a real "Save as" (an `<a download>` on a cross-origin URL would only display it), with a
new-tab fallback and a deferred `revokeObjectURL` (large-blob safety). The endpoint is
entitlement-gated server-side (staff any in-school; a student only media they appear in; else 404).

### 5. Appearances + shared primitives

- **`AppearanceList`** — name + a "Review" warning pill (`needs_review`) + confidence percent
  (`tabular-nums`); shared by the Lightbox and the photo page.
- **`FilterChips`** — a **`radiogroup`** (role=radio + aria-checked) for the single-select
  by-student / appears-in selectors — the correct "pick one of N" semantics (not a bag of
  `aria-pressed` toggles). Shared, so the a11y fix lives in one place.
- **`useDownloadToDisk`** — the download flow (blob save + fallback + `downloading` flag), shared by
  the two download buttons.
- **`tabs.tsx`** — Radix Tabs, underline style (dep **`@radix-ui/react-tabs`**).

### 6. `media_id` vs `id` — the load-bearing contract detail

Browse-all returns `MediaResponse` (`id`); the gallery endpoints return `GalleryMediaResponse`
(`media_id`). Both are normalised to a plain `mediaIds: string[]` at each call site before reaching
`PhotoGrid` — a swap would type-check but 404 every tile, so it was verified explicitly.

## Alternatives rejected

- **A thumbnail/resize endpoint** — none exists; v1 renders full-res tiles behind the lazy gate.
  Thumbnails are the obvious perf follow-up.
- **`next/image` for tiles** — masonry needs natural aspect ratios from unknown-dimension signed URLs;
  a plain `<img>` (with the documented `no-img-element` waiver) is the pragmatic fit.
- **`aria-pressed` toggle chips** — wrong semantics for single-select; `FilterChips` is a radiogroup.
- **A separate `LightboxImage`** — folded into the shared `SignedImage` (used by tile + lightbox +
  photo page), which also gave the photo page a terminal-failure state for free.
- **Adjacent-image prefetch in the Lightbox** — deferred (a brief spinner on nav is acceptable v1).

## What this phase does NOT do (deferred, documented)

- **Live smoke not run** — Docker is down, so the entire read path is unverified: the gallery joins
  (who-appears-where), the **signed download URL**, and the actual **image render/download** from
  Supabase. Run it once the stack is up (needs processed events with `matches`).
- No thumbnails/resizing; no adjacent-image preload; no arrow-key roving within the chip radiogroup
  (plain Tab works; a Radix ToggleGroup would add roving later); video isn't specially rendered.

## Testing

- Gate green (`eslint` + `tsc --noEmit` + `next build`, Node 22) after each review round. No backend
  change.
- **2× review→fix loop.** R1 (correctness) — two agents (engine + screens): **no blockers, no
  should-fix**; the `media_id`/`id` usage, lazy-load, expiry re-mint, and Lightbox nav/focus were all
  verified sound. R2 (design/a11y/edge) — two agents: **no blockers**; tightened the masonry gutter
  (12→8px) and fixed the tile hover (design), and added the **`aria-live`** counter, ordinal tile
  labels, deterministic Lightbox focus, the radiogroup chips, and the **`SignedImage` /
  `useDownloadToDisk` / `FilterChips`** extractions (which fixed the photo page's missing failure
  state + the Lightbox fetch-error gap by construction).
- Live smoke **pending** the stack (above).

## Files

- **New:** `app/(school)/events/[eventId]/gallery/page.tsx`, `app/(school)/photos/[mediaId]/page.tsx`;
  `components/gallery/{photo-grid,photo-tile,lightbox,signed-image,appearance-list,filter-chips,
  grid-skeleton}.tsx`; `components/ui/tabs.tsx`; `lib/api/download.ts`; `lib/hooks/{use-in-view,
  use-media-download,use-galleries,use-download-to-disk}.ts`.
- **Changed:** `app/(school)/students/[studentId]/page.tsx` (+ Appears-in), `app/(school)/events/[eventId]/page.tsx`
  (+ View-gallery link); `lib/api/{types,endpoints}.ts` (gallery surface); `package.json`
  (`@radix-ui/react-tabs`). **No migration, no backend change.**
