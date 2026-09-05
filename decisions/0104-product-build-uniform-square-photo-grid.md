# 0104 — Uniform square photo grid (every tile the same size)

**Date:** 2026-09-05
**Status:** Accepted (revises the natural-aspect masonry of [0035](0035-frontend-galleries-and-download.md) / BP3 [0040](0040-product-build-BP3-student-receive-experience.md) / BP20 [0075](0075-product-build-BP20-arrival-moment.md))

## Context

Every photo grid rendered through `PhotoGrid`/`PhotoTile` used a CSS multi-column **masonry**
(`columns-2 sm:columns-3 lg:columns-4`) where each tile took the image's **natural aspect** — so a
mix of portrait + landscape photos produced **uneven tile sizes** (the Pinterest look). The
`aspect-square` / `aspect-[3/4]` classes only shaped the loading *placeholder*; once the image
loaded, `SignedImage`'s `<img>` was `w-full` with natural height.

The owner asked: **wherever images are shown in a group, each image should sit in a fixed
square/rectangle so every image reads as the same size**, regardless of the original's dimensions.

## Decision

Make every `PhotoGrid` tile a **fixed uniform square, cropped to fill (`object-cover`)**, laid out
in a **real CSS grid** (row-major) instead of the column masonry. **FE-only — no backend/ML change,
no migration, no new dependency, no new permission.** One chokepoint (`PhotoGrid` + `PhotoTile`)
covers every group surface: the event gallery (All photos / By student), the student-detail "Appears
in", and the student `/me` gallery.

- **`photo-grid.tsx`** — container `columns-*` → `grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4`
  (gap 3 masonry / 2 grid); dropped `break-inside-avoid` + the per-child bottom margins.
- **`photo-tile.tsx`** — both tiles' loaded `<img>` gains `aspect-square w-full object-cover`
  (fill + crop). `MasonryTile` also switched its wrapper to `aspect-square` and `loading="block"` →
  `loading="square"` so its placeholder is a square too (no reflow).
- **`grid-skeleton.tsx`** — the loading skeleton switched from column-masonry varying-height tiles
  to a matching uniform square grid (no pop when real tiles resolve).

The **`variant`** prop ("grid" staff / "masonry" student) now only picks the **chrome** (grid =
bordered + selectable; masonry = rounded + hover zoom + hover-download) — both are the same uniform
square. The **Lightbox, the single-photo detail page, and avatars are untouched** — a tile is a
uniform cropped square, but opening a photo still shows the **full image uncropped**.

The review round also caught one **hand-rolled** group grid outside `PhotoTile` — the event
gallery's **Needs-review lane** tile (`events/[eventId]/gallery/page.tsx`) — which had a square
wrapper but no `object-cover` on its `<img>`, so it wasn't actually uniform; brought it into the
same `aspect-square … object-cover` treatment so "same size everywhere" genuinely holds.

## Alternatives considered

- **A landscape rectangle (4:3 / 3:2)** — often "looks right" for event group photos (preserves the
  sides a square center-crop drops). Chose **square** as the most uniform, standard "same size"
  default (Instagram / Google-Photos thumbnails); the aspect is a **one-line change**
  (`aspect-square` → `aspect-[4/3]`) if the owner prefers a landscape tile.
- **Keep the student masonry natural-aspect** (BP20's "arrival moment") — overridden by the owner's
  "same size everywhere"; the student surface is dormant in v1 anyway (no student login).

## Honest limits / notes

- **Crop caveat:** this is a face app — a square `object-cover` **center**-crop of a wide group
  photo can cut people at the edges **in the thumbnail**. The full image is always one tap away in
  the Lightbox, and `object-position` is the default (center). If edge-cropping proves a problem, a
  landscape aspect (above) or a smarter crop is the follow-up.
- **Tile order** is now **row-major** (left→right, top→bottom) — a fix vs the column masonry's
  column-major reading order.
- `SignedImage`'s `loading="block"` mode now has no callers (kept as a valid API; harmless).

## Verification

- FE lint + tsc + `next build` green. No backend/ML suite delta.
- **Review loop (+ self-review) — SHIP, 0 blockers.** Verified the loaded `<img>` genuinely becomes
  a cropped square in both variants (placeholder box == final box → no layout shift), the
  `columns → grid` swap doesn't regress the windowing sentinel (still a sibling, not a grid cell),
  the Lightbox open-index alignment, selection mode, video poster tiles, or the masonry hover
  scrim/download, and the skeleton matches. Its one actionable finding — the **Needs-review lane**
  hand-rolled tile still rendered natural-height (no `object-cover`) — was fixed (above). Nits noted
  and accepted: the crop caveat (below), the now-row-major tile order (an improvement), and the
  now-callerless `loading="block"` mode (kept as a harmless API).
