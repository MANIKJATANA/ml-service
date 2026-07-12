# 0034 — Frontend events + media upload + processing (Phase F4)

**Date:** 2026-07-13
**Status:** Accepted

## Context

F3 ([0033](0033-frontend-staff-and-students.md)) delivered the enrollment half (staff + students).
**F4 delivers the async inference half from the UI**: event CRUD, **multi-file** event-photo upload
straight to Supabase, and the event-level **"Process"** action with **live status polling**, all against
the Phase-5 backend ([0027](0027-events-media-enqueue-status.md)). The backend contract was already
complete, so **F4 needs no backend change** — `EventResponse`, `MediaResponse`, and
`EventStatusResponse{processing_status, pending, completed, total}` carry everything the UI needs.

## Decisions

### 1. Screens (`(school)` group — school_admin / teacher)

- **`(school)/events`** — a `Table` (name → detail, date, **processing** pill) + a **Create-event
  `Dialog`** (name, description `Textarea`, optional date). Archived events are flagged with an inline
  "Archived" pill rather than a separate column (§6).
- **`(school)/events/[eventId]`** — event info + an **Edit `Dialog`** (partial `PATCH`; an emptied
  optional field is omitted since the backend can't clear to null), **Archive** (`ConfirmDialog`) /
  **Restore**, and a **"Photos"** card: a `ProgressBar` + counts + the **Process/Redistribute** button
  wired to `useEventStatus` (§3–§4).
- **`(school)/events/[eventId]/upload`** — the multi-file uploader (§2): a `MultiFileDropzone`, a
  per-file status/progress list, and a "Back to event" that revalidates the event's status/media keys.

### 2. Multi-file upload (`uploadEventMedia` + `useMediaUpload`)

`lib/api/upload.ts` was refactored to share `assertImage`/`assertSize`/`putToSignedUrl`; the new
`uploadEventMedia(eventId, file)` runs **mint (per-event signed URL) → XHR PUT straight to Supabase →
register** the `media` row, returning the created media. `useMediaUpload(eventId)` manages the batch: a
**bounded-concurrency pool** (3 workers sharing an index — `idx++` between awaits guarantees no file is
taken twice) tracks per-file `{status, progress}` by a stable local id, **isolates a failed file**
(marked `error`, never aborts the batch), and derives `isUploading`/`summary` from the item list. A
`mounted` ref guards `patch` against setState-after-unmount (the breadcrumb can unmount mid-upload;
in-flight PUTs still register server-side). Images only in v1 (`media_type: "image"`). An orphaned
object on a register-after-PUT failure is accepted (swept by a storage lifecycle policy; the FE can't
delete via an upload-only URL).

### 3. Live status polling (`useEventStatus`)

SWR with a **function `refreshInterval`**: `2500` ms while the event is `queued`/`processing`, `0`
(stop) otherwise. Because the arrow is a fresh reference each render, the polling effect re-arms
whenever the data changes — so it **starts** if the first fetch lands in-flight and **stops** the moment
a fetch returns `completed`. A transient status-endpoint 500 keeps the last-good data (so polling
continues and recovers); `shouldRetryOnError:false` is global.

### 4. Process semantics + resilience

The **Process** button shows only when actionable — event **active**, **not in-flight**, and
**`pending > 0`** — labelled "Redistribute" once a run has completed but left pending photos. On click:
`processEvent` → `eventMutate(updated)` + `globalMutate("events")` → **optimistically flip status to
`queued`** then revalidate. The optimistic flip means a slow/failed status refetch can't strand the UI
(the pill + poll re-arm immediately; a failed revalidate keeps polling on the optimistic `queued`). The
three backend `400`s ("event is archived" / "already queued or processing" / "no pending photos") and
`502` (queue down) all surface as the `{detail}` toast. Archived events hide upload/process client-side
(the backend `400` is the backstop).

### 5. Processing pill derived from counts

The event's `processing_status` stays `completed` after a finished run even when new photos are
uploaded (`pending > 0`), so echoing it would show a green "Completed" pill above a "Redistribute"
state. The pill is therefore derived: in-flight → the live status; else → `completed` only when
`total > 0 && pending === 0`, otherwise `not_started`. It can never contradict the counts/CTA.

### 6. Status-pill tones — colour only when something is happening

`lib/events/status.ts`: `active`/`archived`/`not_started`/`queued` are **neutral**, `processing` is
**info** (blue = live), `completed` is **success** (green). This reserves colour for the states that
matter (running / done) instead of painting every active row green (the references keep one semantic
colour for the rare signal). The events table shows a single **processing** pill per row + an inline
neutral "Archived" flag — the low-information lifecycle column was dropped.

### 7. New primitives + shared helpers

- **`textarea.tsx`** — mirrors `input.tsx` (border/radius/focus/disabled/invalid) with a multi-line
  min-height; used for event descriptions.
- **`multi-file-dropzone.tsx`** — the `file-dropzone` treatment, `multiple`, stateless (hands files up).
- **`button.tsx`** now exports `buttonVariants` so a `<Link>` can be styled as a button (the "Upload
  photos" / "Back to event" navigations are real anchors, not `router.push` buttons).
- **`lib/events/status.ts`** — the shared tone/label maps (single source of truth).

## Alternatives rejected

- **A shared `EventForm`** for create + edit — they diverge (reset-on-close + POST vs re-seed-on-open +
  changed-fields diff + "no changes" path); at N=2 an abstraction obscures more than it saves.
- **Video upload** — the backend supports `media_type: "video"`, but the 30 MB cap makes it impractical
  and the galleries are photo-first; images-only in v1, structured so video is a small later addition.
- **A per-media roster/thumbnails on the detail page** — the `status` endpoint's counts are the right
  F4 summary; thumbnails need per-media signed download URLs (F5 galleries). `MEDIA_STATUS_*` tone maps
  were dropped until that lands.
- **Whole-row-click events table** — kept F2's name-link + row-hover pattern (consistent, simpler).

## What this phase does NOT do (deferred, documented)

- **Live smoke not run** — Docker Desktop is down. The unverified path is the whole async round-trip:
  Supabase signed **PUT** + register, then **Process → ML worker → status columns → the FE poll**
  advancing `queued → processing → completed`. Run it once the stack (backend + Redis + ML worker +
  Supabase) is up.
- No video; no media thumbnails/roster (F5); no list virtualization for very large batches (the pool
  caps concurrency at 3; rows are light); no ceiling on polling a permanently-stuck `processing` event.

## Testing

- Gate green (`eslint` + `tsc --noEmit` + `next build`, Node 22) after each review round. **No backend
  change**, so the backend gate is unaffected.
- **2× review→fix loop.** R1 (correctness) — two agents (engine + screens): **no blockers**; contract
  verified exact, the upload pool confirmed race-free, polling stop/start/restart confirmed. Fixed the
  derived pill, added the upload-manager unmount guard, documented the orphan-on-register tradeoff, and
  polished comments/hints. R2 (design/a11y/edge) — two agents: **no blockers**; retoned the status pills
  (§6), added the **`aria-live`** processing region (the key silent change), bumped load-bearing
  `ink-muted`→`ink-secondary` (AA), made Process **optimistic** (§4), and removed a dead `reset` export.
- Live smoke **pending** the stack (above).

## Files

- **New:** `app/(school)/events/[eventId]/page.tsx`, `app/(school)/events/[eventId]/upload/page.tsx`;
  `components/ui/{textarea,multi-file-dropzone}.tsx`; `lib/hooks/{use-events,use-event-status,
  use-media-upload}.ts`; `lib/events/status.ts`.
- **Changed:** `app/(school)/events/page.tsx` (was the F1 placeholder); `lib/api/{types,endpoints}.ts`
  (event/media surface); `lib/api/upload.ts` (shared helpers + `uploadEventMedia`); `components/ui/button.tsx`
  (`buttonVariants` export). **No migration, no backend change.**
