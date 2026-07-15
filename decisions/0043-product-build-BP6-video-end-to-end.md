# 0043 — Product Build BP6: Video end-to-end

**Date:** 2026-07-15
**Status:** Accepted

## Context

The roadmap phase after BP1–BP5 (`product/03` §3, BP6). Video is **fully built in the ML service** — frame
extraction, per-frame matching, timestamps, and a rich detection audit (`media_detections`/`media_frames`/
`face_detections`/`face_detection_candidates` + the `student_media_appearances` view, decisions/0021) — but **dark**:
no UI ever rendered a video, and the event uploader refused non-image files. Fails lens **X6**, target **T6**. This is
a **surfacing** phase, not a capability build.

Grounding facts (verified by exploration before design):
- `media_type: "image" | "video"` already flows end-to-end — the backend `media` table (CheckConstraint), the
  domain model, **and** every gallery/media response schema — and it's already in the FE types
  (`MediaResponse.media_type`, `GalleryMediaResponse.media_type`, `MediaReviewResponse.media_type`). The FE simply
  never branched on it.
- `registerMedia(eventId, path, mediaType)` and the backend `RegisterMediaRequest.media_type: MediaType` accept
  `"video"` with **no image-only guard** anywhere in the register path → registering a video needs **zero backend
  change**.
- The signed **download** URL is minted with a plain Supabase `create_signed_url` — **no `download` disposition, no
  transform** — so the object is served inline with its stored content-type and Supabase honours **range requests**.
  The same URL the `<img>` already renders inline therefore streams (and seeks) in a `<video>` unchanged.
- The download blob-save path (`downloadToDisk`) is already media-agnostic (extension from the blob MIME).

**Owner decision (this session):** ship **Core now, defer the timeline.** Core = video upload + render + play +
download + the (BP5-overlay-correct) appearances list, **FE-only, no backend/ML change, no migration**. The roadmap's
"ideally a timeline of who appears when" is deferred — it's the one part that needs a net-new backend read (see
Follow-ups).

## Decisions

### 1. Render video off the same signed URL — one branch in `SignedImage`
`SignedImage` (the shared media primitive, decisions/0035) gains `kind?: MediaType` (default `"image"`) and
`asPlayer?: boolean`. When `kind === "video"`:
- **`asPlayer` (lightbox / photo-detail)** → a full `<video controls playsInline>` off `download.download_url`.
- **poster (grid tiles, default)** → a muted, non-interactive `<video preload="metadata" tabIndex={-1}
  aria-hidden>` with the URL fragment `#t=0.1` (nudges the browser to paint a first frame — a bare `<video>` can
  stay blank) and `pointer-events-none` so the click falls through to the wrapping tile button.

The existing lazy-gate (`enabled`), one-shot 403 re-mint (`onError` → `mutate`), and terminal fallback all apply
unchanged to the `<video>` (the handler was renamed `onImgError` → `onMediaError`). Images render exactly as before.

### 2. Thread the media type through the grid via `items`
`PhotoGrid`'s prop changed from `mediaIds: string[]` to **`items: GalleryItem[]`** (`{ id, mediaType }`) — a single
source of truth per media. Internally it derives two index-aligned arrays: `mediaIds` (for the Lightbox's existing
index-based nav / download / keys) and `mediaTypes` (passed to the Lightbox as `mediaTypes?: MediaType[]`, read as
`mediaTypes[index] ?? "image"`). `PhotoTile`/`GridTile`/`MasonryTile` take a `mediaType` and overlay a **play badge**
on videos (`pointer-events-none`, centred). All five callers now pass `items` (they already had `media_type` on their
rows): the event gallery (All / By-student), the student-detail "appears in", the student `/me` masonry (which keeps
its separate `mediaIds` memo for `useDownloadAll`), and the needs-review thumbnails + photo-detail page pass `kind`
directly to `SignedImage`.

### 3. Upload accepts video
`uploadEventMedia` replaces the hard `assertImage` + hardcoded `"image"` with `mediaTypeOf(file)` — classify by MIME
(`image/*` → `image`, `video/*` → `video`, else reject) and register with the detected type. The dropzone gets
`accept="image/*,video/*"` + generalized copy ("Photos & videos"); the size error is generalized ("File is too large").
`uploadReferencePhoto` keeps `assertImage` — student reference photos stay image-only.

### 4. Copy / a11y made media-aware
Tile aria-labels ("Open video N" vs "Open photo N"), the Lightbox sr-only title/description ("Media viewer" / "move
between items"), the Lightbox + photo-detail "In this {video|photo}" headings, and the photo-detail breadcrumb
("Video" vs "Photo") + alt text now branch on the type.

## Honest limits (documented, not bugs)

- **Video size is bounded by the existing per-upload cap** (`BE_MAX_UPLOAD_MB`, default **30 MB**) and the Supabase
  bucket's own file-size limit — the FE respects whatever `max_upload_mb` the mint returns. Longer clips need the
  backend cap raised **and** the bucket limit raised (infra) — deliberately out of this FE-only Core (a one-line
  settings + infra follow-up if wanted).
- **No poster thumbnail is generated** — the grid poster is the browser-rendered first frame (`#t=0.1`), not a
  stored thumbnail. Fine for v1; a real thumbnail is an ML/worker follow-up.
- **Arrow keys in the lightbox navigate items even when a focused `<video>` would otherwise seek** — the window
  keydown listener wins and the element remounts on nav. Acceptable; scrub via the player's own timeline.

## Verification

- FE gate green: `tsc --noEmit` + `eslint` + `next build` (16 routes).
- **2× review→fix loop.** R1 (correctness): traced the video path end-to-end — playback/download reuse the
  inline-served signed URL (confirmed no `download` disposition in `supabase_store._sign_download_sync`), the `#t=0.1`
  poster fragment is valid after the token query, and `mediaTypes[index]` stays aligned to `mediaIds` (both derived
  from one `items` array); reverted a stray `object-cover`/`aspect-square` on `GridTile` that would have changed the
  existing image layout (the staff grid is CSS-`columns` masonry, natural aspect). R2 (edge/a11y/copy): made the
  headings/labels/alt media-aware, generalized the dropzone copy, kept `assertImage` for reference photos.
- **No backend/ML change, no migration, no new dependency.** The backend register + download + Supabase adapter
  already supported video; only the FE branched.

## Follow-ups

- **The "who appears when" timeline** (the roadmap's "ideally") — a new isolated `db/ml_audit_read.py` seam over the
  `student_media_appearances` view (read-only Core table, kept out of `Base.metadata` like `ml_read.py`) + an
  `MlTimelineReader` port + `GET /v1/media/{id}/timeline`, **overlaid against the BP5 corrections** (rejected students
  dropped), rendered as a per-student seek-on-click strip in the video lightbox. Small BE read; no migration.
- Raise the video size cap (backend `BE_MAX_UPLOAD_MB` + Supabase bucket limit); generate a real video **poster
  thumbnail** in the ML worker. **Next: BP7** (per `product/03`).
