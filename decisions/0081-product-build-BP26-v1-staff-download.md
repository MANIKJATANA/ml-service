# 0081 — Product Build BP26 (v1): Staff per-student "Download all" (the v1 distribution model)

- **Date:** 2026-08-30
- **Status:** implemented (FE gate green; 2× review loop clean)
- **Phase:** **BP26 (v1)** — the v1 *distribution mechanism*, from the Round-4 staff/admin review
  ([`product/08`](../product/08-product-review-round-4-staff-admin.md) finding **R4-D00**) + roadmap
  ([`product/09`](../product/09-improvement-roadmap-round-4.md) Tier-0). **FE-only — no backend/ML change, no
  migration, no new dependency, no new permission, no new env var.**

## Context — the v1 pivot (owner decision, 2026-08-29)

The owner set the v1 scope: **there is no student login in v1.** Students do not access the app; the whole
`(student)/me` surface + student credentials + the in-app "announce → opened" loop are **dormant** in v1 (the code
stays, unused). **Distribution is staff-mediated:** a teacher or school-admin **downloads a student's photos and
shares them (e.g. via WhatsApp) themselves** — the staff member *is* the delivery channel.

This reframes the Round-4 review's one Blocker (**R4-D00**). It is no longer "no outbound email reaches students"
(that — the original BP26 / **BP12** — is now **parked post-v1**, see [`product/05`](../product/05-parked-backlog.md)
and [`product/09`](../product/09-improvement-roadmap-round-4.md)); it is that **staff have no per-student "download
all"**. Today staff can download a *single* photo (lightbox/detail) or an *event's whole gallery* (BP13 select →
download), but **not "every photo of student X across all their events"** in one zip — the exact bundle they need to
hand a parent. A student could already do this for *themselves* (`(student)/me` "Download all", BP3/BP9/BP20); v1
needs the **staff-side** equivalent.

Two Explore/verification passes confirmed the whole thing is **frontend-only**: the read endpoint, the download
entitlement, and the streaming-zip hook all already exist.

## Decision (all FE — mirrors the student self-view, staff-side)

A **"Download all N photos"** action on the **student detail** page (`app/(school)/students/[studentId]/page.tsx`),
in the header of the existing **"Appears in"** section, available to **teacher *and* school-admin**.

### The read — one new hook, reusing an existing staff endpoint
- `lib/hooks/use-galleries.ts` gains **`useAllStudentMedia(studentId)`** → `GET /v1/students/{id}/media` **with no
  `event_id`** = the student's *full effective photo set across all events* (rejected matches excluded, staff-added
  included — the BP5 overlay, applied server-side by `GalleryService`). SWR key `students/{id}/media` — a **distinct**
  key from the per-event `useStudentMedia`'s `students/{id}/media?event_id=…`, so the two caches never collide.
- The route is gated by **`gallery:view_all`**, which **both** staff roles already hold; the per-photo download mint
  (`GET /v1/media/{id}/download`) is the **same** entitlement-gated path staff already use in the event gallery. **No
  permission is widened and no gate is bypassed.**

### The download — reuses `useDownloadAll` verbatim
- A new `StudentDownloadAll` component feeds the student's media ids into the existing **`useDownloadAll`** streaming
  zip (client-zip → File System Access API on Chromium/Edge, buffered fallback elsewhere — BP3/BP9/BP20/BP24b), with
  an `entryBase` foldered by **event/date** (`{Event}/{date}-nnn.jpg`) built from the already-fetched
  `useStudentEvents` list, and a `zipName` of **`{Student-Name}-photos-{date}.zip`** (`sanitizeFilename`, `"student"`
  fallback). This is the same naming pattern as the student self-view (BP20).
- **Honest states, reused:** `cancelled` → silent; `saved === 0` → error toast; `capped` (non-streaming >500) → "the
  first N of M…"; `0 < saved < total` → "saved N of M…"; full → a success toast. Copy **mirrors the sibling *staff*
  surface** (the event-gallery download) for cross-surface consistency (success-toast-on-full, not the student
  masonry's silence).
- **A11y:** the button label flips to `Preparing {done}/{total}…` while busy (sighted feedback), plus a single
  `sr-only aria-live="polite"` node — matching the self-view, and deliberately **not** a *visible* per-tick live
  region (which would announce on every photo). The icon is `aria-hidden`; the button is disabled while the list
  loads / while busy.

### Gating (nothing new; correct by construction)
- The button lives inside `AppearsInSection`, which **only renders when the student appears in ≥1 event** — so a
  photoless/unmatched student shows **no** button (nothing to download). A loaded-but-empty set or a list-read error
  → the button hides (the per-event view still works).

## Files changed (2)

- `frontend/lib/hooks/use-galleries.ts` — **+`useAllStudentMedia(studentId)`** (the full-set read).
- `frontend/app/(school)/students/[studentId]/page.tsx` — **+`StudentDownloadAll`** component (in `AppearsInSection`'s
  header); `AppearsInSection` gains a `studentName` prop threaded from the page; new imports (`Download`,
  `useCallback`/`useMemo`, `useDownloadAll`, `useAllStudentMedia`, `EventForStudentResponse`, `sanitizeFilename`,
  `toISODate`).

## Out of scope (documented)

- **Outbound email/SMS to students** (the original BP26 scope) — **parked as BP12**, post-v1: no student login → no
  inbox to reach.
- **WhatsApp integration** — v1 share is **manual** (staff saves the zip, then shares it themselves); no deep-link /
  auto-send.
- **The dormant student surface / student credentials** — untouched. A "v1 hygiene" cleanup (hide the shown-once
  *student* temp-password step in create/bulk-import; hide the `(student)/me` surface) is noted in `product/09` as an
  optional companion, **not** built here.
- **A per-student download on the event gallery "By student" tab** (an event-scoped bundle) — an easy cheap
  follow-on; not built here (the student-detail all-events bundle is the requested "download-all at student level").

## Verification

- **FE gate green:** `npm run lint` + `npx tsc --noEmit` + `next build` all pass; `/students/[studentId]` stays
  `ƒ` (dynamic), unchanged. No backend/ML suite delta (nothing backend changed).
- **2× review loop** (two independent review agents):
  - **R1 (correctness):** **0 blockers, 0 should-fix.** Verified — hooks are unconditional before the early returns
    (no conditional hooks); `entryBase(i)` and `mediaIds[i]` close over the same `media` in the same order (aligned);
    all `{saved, capped, cancelled}` branches + the throw-path `catch` handled; the entitlement reuses the existing
    mint (no widening); the SWR keys don't collide; `AppearsInSection` regressions none. One NIT (the intended
    disabled-while-loading label) — no change.
  - **R2 (edge/a11y/copy/simplification):** **0 blockers.** Confirmed placement (keep it in the section header, not
    the crowded page-header row), `sanitizeFilename` robustness (long/emoji/slash → sane, empty → fallback), video
    handled (extension from content-type), the separate hook warranted. **Applied its two should-fixes:** (1) the
    a11y fix — replaced the *visible* per-tick `aria-live` with the label-flip + `sr-only` live region (matching the
    self-view); (2) harmonized the toast copy with the sibling staff event-gallery surface + added an
    effective-vs-raw-count comment (the button counts the BP5 *effective* set; the EngagementCard's
    `photos_appearing` is the raw aggregate — a legitimate, documented divergence).

## Honest limits (documented)

- **Non-streaming browsers (Firefox/Safari) cap a single zip at 500 photos** (the pre-existing BP9 `BUFFERED_CAP`) —
  a >500-photo student there gets the first 500 + a "open in desktop Chrome or Edge" note. Rare per single student;
  Chromium/Edge streams the full set.
- **"All photos" = the student's EFFECTIVE appearances** (BP5): a photo still `needs_review` **is** included (staff
  decide — same as the student would have received); a rejected match is excluded. This can differ momentarily from
  the EngagementCard's raw `photos_appearing`.
- **One extra list read per student-detail visit** (`useAllStudentMedia`), even if the staffer never clicks Download
  — a lightweight id/type list (not bytes), needed for the accurate button count; acceptable.
- The zip is built client-side from N per-photo signed URLs (bounded memory on Chromium/Edge; buffered elsewhere) —
  identical to the student self-view's proven path.

## Notes

- This is the first phase off the **Round-4 (pre-release, staff/admin) roadmap** (`product/08`/`product/09`). It
  closes the review's one Blocker (**R4-D00**) for v1. The remaining Round-4 tiers (BP27 bulk-ops parity · BP28
  governance/audit · BP29 teacher coherence · BP30 review tools · BP31 onboarding/copy) stay unscheduled; a phase
  starts only on owner pick + scope re-confirm.
