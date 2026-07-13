# 0040 — Product Build BP3: Student receive experience

**Date:** 2026-07-14
**Status:** Accepted

## Context

Third phase of the product-improvement build track (roadmap `product/03`). The student `/me/events` gallery — the
product's emotional core and the one surface held to the **Pinterest bar** (image-first, warm, immersive) — was
"Linear-plain": every tile was **square-cropped** (so the photo wasn't the hero), with no warmth, no context, no
"new since," and no bulk save. This phase makes it feel like the recipient's own private album. **Frontend-only —
no backend change, no ML change.** One new (tiny, zero-dependency) client dep: `client-zip`.

## Decisions (BP3)

### 1. Real masonry — the photograph is the hero (a `variant` on the shared grid)
`PhotoTile` split into **`GridTile`** (staff: uniform square crop, bordered — byte-identical to before) and
**`MasonryTile`** (student: **natural aspect ratio** in the columns, borderless rounded tiles, a restrained
`group-hover` zoom, and a **hover-revealed download** so a photo saves in one tap without opening the viewer).
`PhotoGrid`/`PhotoTile` gain a `variant` prop defaulting to `"grid"`, so **every staff caller is unchanged**; the
student page passes `"masonry"`. `SignedImage` gains a `loading="block"` placeholder (aspect reserved until the
natural image loads and the column reflows — inherent to masonry without stored dimensions).

### 2. Warm page framing (copy from the user's side)
A hero — "Your photos", "You're in N photos from M events. **Only you can see these.**" — plus a **first-visit
welcome** and a **"N new since your last visit"** chip, both client-tracked (`useNewSince`, localStorage per
`userId`; the seen-set is folded forward each visit). `firstVisit` (no stored set) shows the welcome, never a
misleading "everything is new". The commit waits for a **settled, non-empty** all-events roster so a transient/empty
SWR read can't lock in an empty seen-set. The read is deferred to a post-paint `rAF` callback — client-only, no
hydration mismatch, and the `setState` lands in a callback (not synchronously in an effect, per the repo's lint rule).

### 3. Download-all — one client-side zip, no server change
`useDownloadAll` mints each entitled signed URL, fetches the bytes (bounded concurrency 4, order-preserving,
**skips** a photo that fails rather than failing the whole archive), and streams them into one `my-photos.zip` via
`client-zip`. It resolves with the saved count so the page **acknowledges a partial result** (toast "Downloaded X of
N …") and throws only if nothing could be fetched. Progress is announced (`aria-live` sr-only "Preparing X of N").
Known v1 limit (documented in the hook): the archive is buffered in memory — fine for a student's modest set; a
streaming save is the scale-up.

### 4. Reduced-motion floor actually enforced (D8)
Added a global `@media (prefers-reduced-motion: reduce)` reset to `globals.css` collapsing transitions/animations
app-wide — covering the new hover zoom, the skeleton pulses, the spinner, and the lightbox transitions. **This
closes a real gap:** F7 ([decisions/0037](decisions/0037-frontend-polish-and-hardening.md)) listed "reduced-motion
respected" but never enforced it globally; BP3 does.

### 5. Privacy preserved
Appearances stay hidden for students (the `showAppearances={false}` path from F6 — the `/appearances` endpoint is
staff-only and other students' names must not leak). Download stays entitlement-scoped (own media only). The masonry
skeleton matches the tiles' radius/gutter so nothing pops on load.

## Verification

- FE gate green: `eslint` + `tsc --noEmit` + `next build` (Node ≥ 20.9). **No backend change** (backend suite
  untouched, still 258/17).
- **2× review→fix loop:** round 1 (correctness/hooks/download) fixed the `useNewSince` transient-empty commit
  (gate on a settled non-empty set) and confirmed the zip worker pool is race-free + SSR-safe; round 2
  (design/a11y against the Pinterest bar) added the global reduced-motion guard, the download-all progress
  announcement + partial-failure acknowledgement, and the skeleton radius/gutter parity. Staff galleries confirmed
  unchanged (`variant` defaults to `"grid"`).

## Follow-ups (roadmap `product/03`)

Deferred (documented): streaming zip for very large galleries; a richer "new photos" signature moment; the lightbox
could gain per-photo event context (needs the media→event name threaded in). **Next: BP4 — Distribution ("photos are
ready")**, the flagship — the first phase that needs **net-new backend + a migration** (in-app "new photos" state,
then email), so it'll be scoped/locked in its own decision doc first.
