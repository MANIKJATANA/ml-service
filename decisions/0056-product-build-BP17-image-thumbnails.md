# 0056 — Product Build BP17: Image thumbnails

**Date:** 2026-07-25
**Status:** Accepted (implemented)

## Context

Every list and gallery loaded **full-resolution** images: a ~900-photo student gallery pulled 900
full-size photos just to render grid thumbnails, and the student list showed no face preview at all
(`StudentAvatar.photoUrl` was wired in F3 but never populated). BP17 — the fast-UI companion to BP9
(`product/04`, decision [0054](0054-product-review-round-2-and-BP9-roadmap.md)) — serves a **small
low-res image** for previews (grid/masonry tiles + the student-list/detail avatar) and keeps
**full-res** for the lightbox + download.

> **Mechanism history (two supersessions).** (1) A first draft used **on-the-fly Supabase image
> transforms** on the signed URL — reverted before commit because transforms are a **Pro-plan**
> feature. (2) A second draft used **"save-twice"** — the *browser* compressed a copy and PUT it to a
> `{uuid}.thumb` key. In practice that never stored a thumbnail: **the PUT to a `.thumb`-suffixed key
> fails** (Supabase/content-type rejects the unknown extension), so `thumbnail_path` stayed null and
> every tile fell back to full-res (the "list shows the full photo" bug). Owner decision: **generate
> the thumbnail in the backend** and drop the `.thumb` suffix. This doc describes that shipped design.

## Decision

**The backend generates the thumbnail.** The frontend uploads only the original to Supabase; on
register/create the backend **downloads that object, compresses it, uploads a small JPEG sibling** (a
`thumb-{name}.jpg` key), and persists the path. Deterministic thumbnails for every image, on any plan,
not dependent on the browser. **No ML change**; **no migration** (columns exist from `0012`); one new
backend dependency (Pillow).

- **Pillow behind a `Thumbnailer` port (layering-safe).** A new `Thumbnailer` domain port
  (`make_thumbnail(bytes) -> bytes | None`) with a single `adapters/imaging/pillow_thumbnailer.py`
  implementation (EXIF-transpose → RGB → resize longest edge to 512 → JPEG q70; `None` on any
  decode/encode failure or a non-image). Pillow is imported **only** in that adapter — `domain`/
  `services` stay image-library-free (the layering test bans `PIL`). `ObjectStore` grows
  `download_bytes` + `upload_bytes` (supabase download/upload in threads; local_fs is a no-op stub).
- **Generate on every image upload path.** A pure `services/thumbnails.py` (`thumb_key` +
  best-effort `generate_thumbnail`) is called by `MediaService.register_media`,
  `StudentService.create_student`, and `set_reference_photo`: image → download original →
  `make_thumbnail` → upload the `thumb-{name}.jpg` sibling (same tenant/event prefix → passes the
  existing path guards) → store the key; **video / a compression failure / a store outage → null**
  (display falls back to full-res). **Best-effort** — a thumbnail failure never fails the upload. The
  photo-replace still best-effort-deletes the *old* original + old thumbnail (BP8e ethos). The mint
  reverts to a **single** upload target (the FE uploads one object).
- **Serve the stored thumb.** `GalleryService.download_url(..., thumbnail=)` behind
  `GET /media/{id}/download?size=thumb|full` (default `full`) and `StudentService.reference_photo_url`
  behind `GET /v1/students/{id}/reference-photo?size=` (`student:manage`, tenant from the token; 404
  photoless/foreign) select `thumbnail_path if (thumb requested AND present) else storage_path`. A
  `MediaVariant` StrEnum gives a free 422 on a bad `size`. The entitlement gate runs before the size
  selection — `?size=thumb` never widens entitlement.
- **Frontend: single upload + condition on the thumbnail.** `lib/api/upload.ts` uploads only the
  original (the browser `image-compress.ts` is gone). Read models expose the thumbnail's presence —
  `StudentResponse.reference_photo_thumbnail_path`, `MediaResponse.thumbnail_path`,
  `GalleryMediaResponse.has_thumbnail` — and the FE requests `?size=thumb` **only when a thumbnail
  exists**, else the full-res object: the student-list avatar (`useStudentReferencePhoto` size), and
  the gallery tiles via a `hasThumbnail` on the shared `GalleryItem`/`PhotoTile`. The lightbox +
  download stay `full`. The create/replace dialogs memoize the uploaded path (a rejected resubmit
  doesn't re-upload).

## Why

- **Reliable + deterministic** — every image gets a real thumbnail regardless of the browser (the
  save-twice failure mode is gone), on any Supabase plan (no Pro transform, no `.thumb` extension).
- **Architecture intact** — the one place image bytes are decoded is a Pillow *adapter* behind a
  `Thumbnailer` port; `domain`/`services` stay pure and the layering invariant holds.
- **No ML change, no migration** — the thumbnail is display-only (the ML pipeline always reads the
  full-res path); the columns already exist from `0012`.

## Alternatives considered

- **On-the-fly Supabase transforms** (draft 1): Pro-plan only. **Browser save-twice** (draft 2): the
  `.thumb`-key upload fails + best-effort browser compression is inconsistent. Both superseded.
- **A background/async thumbnail job:** keeps register latency flat, but the read model can't carry
  `thumbnail_path` immediately (the FE would show full then thumb after a refetch). Deferred — the
  documented scale-up if register latency on big batches matters.

## Consequences

- Uploading an image costs a backend **download → compress → upload** (throttled by the FE's bounded
  upload pool; Pillow resize is fast). Synchronous, so the thumbnail is ready + the read model carries
  it immediately.
- **Honest limits (documented):** no backfill (pre-BP17 rows serve full-res for `?size=thumb`); video
  has no thumbnail (browser poster — the backend doesn't decode video); best-effort (a decode/upload
  failure stores `thumbnail_path=null`); local-fs dev gets no thumbnails (the stub stores no bytes).
- **New:** dep `pillow`; env `BE_THUMBNAILER_IMPL` / `BE_IMAGE_THUMBNAIL_MAX_EDGE` /
  `BE_IMAGE_THUMBNAIL_QUALITY` (in `.env.example`). **No migration, no ML change, no new perm.**
- **Verified.** Backend ruff + mypy + **435 passed / 30 skipped** + layering (`PIL` banned in
  domain/services): the backend generates a `thumb-*.jpg` under the prefix on image register/create;
  video / a failed compress / a store outage → null (best-effort); the stored-path serve + full-res
  fallback on both surfaces (service + route); the entitlement gate fires regardless of size; the
  replace regenerates + deletes the old objects. Frontend tsc + eslint + `next build` green. 2× review
  loop.
