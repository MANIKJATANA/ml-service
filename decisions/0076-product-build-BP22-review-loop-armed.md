# 0076 — Product Build BP22: Review loop, armed (slices 1–3)

- **Date:** 2026-08-16
- **Status:** implemented (gate green; 2× review loop clean)
- **Phase:** **BP22 (Review loop, armed)** — Round-3 review theme **N**
  ([0064](0064-product-review-round-3-ux.md), [`product/06`](../product/06-product-review-round-3-ux.md)),
  slices **1–3** (R3-A3-02 / R3-A3-08 / R3-S2-02 + R3-A3-09). **Slice 4 (the student "This isn't me" safety)
  is BLOCKED by the owner → a separate future decision.** **One phase. FE-only — no backend/ML change, no
  migration, no new dependency, no new permission.**

## Context

Theme N — "put the evidence where the decision is." The teacher's photo-review loop was under-armed:

- **The review lane offered no reference face (R3-A3-02, High — the highest-leverage accuracy fix).** A review tile
  was photo + name + **%** only. A teacher who personally recognizes ~their 2 classes out of 800, asked "Is this
  Priya Sharma? 71%" against a group photo **with no picture of Priya**, was guessing — and a wrong confirm leaks a
  wrong photo to a wrong student (the exact thing BP5 exists to prevent). The fix was already built + teacher-
  permitted: `StudentAvatar` + `useStudentReferencePhoto` (in use on the students list); `GET
  /students/{id}/reference-photo` is `student:manage`.
- **Review debt was invisible at the announce moment (R3-A3-08, Med).** The event detail — home of Match + Announce
  — never mentioned review; `auto_notify` defaults on, so uncertain matches went student-visible the instant
  matching finished. A hurried teacher matched → "All photos matched" → Announced, and found the review lane later
  or never.
- **The triage round-trip reset itself (R3-A3-09 / R3-S2-02, Med).** The gallery Tabs were **uncontrolled** (no
  `?tab=review`); the events-list "N to review" pill was unlinked; "Open photo →" navigated away, so browser-back
  re-landed on the All tab and the teacher re-clicked "Needs review" per photo. Also: the "Needs review (N)" tab
  badge counted **photos** (`reviews.length`), not match **pairs**.

## Decision

All FE-only:

1. **The reference face in review.** A new **`StudentRefAvatar`** ({studentId, name} →
   `useStudentReferencePhoto(studentId, true, "thumb")` → `StudentAvatar`) rendered **before the name** in three
   staff surfaces: the review-lane tile (`gallery/page.tsx` `NeedsReview`, `size-7`), the staff `AppearanceRow`
   (`appearance-editor.tsx`, `size-8`), and the read-only `AppearanceList` (`appearance-list.tsx`, `size-8`). SWR
   dedupes by student (one mint per distinct face); a photoless/404 falls back to initials
   (`shouldRetryOnError:false`); the face is decorative (`alt=""` — the name is always adjacent).
2. **Review debt at the announce moment.** The `DistributionCard` (`events/[eventId]/page.tsx`) fetches
   `useEventReview(event.id)` and derives **`reviewCount = Σ candidates`** (overlay-correct — the read already drops
   corrected pairs). When > 0: a warning-toned **"N matches to review"** link (→ `/events/{id}/gallery?tab=review`)
   and, on "Announce to students" with debt > 0, a **`ConfirmDialog`** ("N still need review — announce anyway?";
   Cancel = go review, Confirm = announce). No hard block (the no-auto-confirm stance stands).
3. **Reachability.** The gallery **Tabs are URL-controlled** — `tab` derived from `?tab=` (`useSearchParams`;
   validated to `all`/`by-student`/`review`, default `all`) + `router.replace(?tab=…,{scroll:false})` on change —
   so a deep-link opens the right tab and browser-back preserves it. The events-list **"N to review" pill is now a
   `<Link>`** to the review tab. The **tab badge counts pairs** (Σ candidates), matching the DistributionCard.

## Why

- **Show the person where the decision is made** — the reference photo already existed one page away; rendering it
  in the review surfaces is the cheapest possible fix for the review lane's core weakness.
- **Catch the hurried announce** — surfacing the debt + a one-click confirm (not a block) respects the teacher's
  time while making "you have unreviewed matches" impossible to miss at the exact moment it matters.
- **URL as the source of truth for the tab** — the smallest change that makes the review lane deep-linkable and
  browser-back-safe, on an already-dynamic route (no Suspense boundary needed).

## Consequences / honest limits (documented)

- **FE-only; no backend/ML/migration/dependency/permission change.** `git status` shows only `frontend/` (5 files +
  the new `student-ref-avatar.tsx`).
- **Slice 4 — the student "This isn't me" safety (a confirm + undo + surface-to-staff, R3-A4-04/S3-04) — is BLOCKED
  by the owner**, a separate future decision. So a student's one-tap removal stays unguarded + unrecoverable for now.
- **Count divergence across surfaces (deliberate, user-visible).** The DistributionCard link + the gallery tab badge
  use the **overlay-correct** pair count (Σ candidates — drops corrected pairs); the **events-list "N to review"
  pill stays a RAW-ML count** (`event.needs_review`, BP5's documented divergence — `event_match_counts` doesn't
  subtract resolved). So after some pairs are corrected, the same event can read "3 to review" in the list but "(2)"
  in the gallery/announce. A per-event resolved overlay on the list is a backend follow-up. The **dashboard "N to
  review"** is itself a school-wide **approximation** (raw − resolved, clamped), not bit-exact vs the per-event sum.
- **A per-student ref-photo mint in the review lane** — each distinct student in the review tab/rows fires one
  signed-URL fetch (SWR-deduped per student, thumb size, 404→initials) — the same bounded pattern as the students
  list (one mint per row). A 60-distinct-student lane ≈ 60 mints.
- **The reference face is staff-only** — `StudentRefAvatar` renders only on staff surfaces (the `(school)` group is
  `AuthGuard`-walled to admin/teacher; the student `/me` lightbox passes `showAppearances={false}`; and the endpoint
  is `student:manage`-gated server-side, so a student token 403s → initials). Verified defense-in-depth — a student
  never sees a peer's enrolled face.
- **The announce-confirm is a soft advisory** — a lane cleared by a colleague between render and click still shows
  the stale count/dialog; it never blocks and `onNotify` proceeds correctly (no re-check on click).
- Verified: FE **lint + tsc + `next build` green** (the gallery route stays `ƒ` dynamic, so `useSearchParams` needs
  no Suspense boundary); no BE/ML suite delta. **2× review loop — no blockers.** **R1** (correctness/privacy) traced
  the staff-only privacy boundary (defense-in-depth to the backend permission), the per-student fetch dedupe/404
  fallback, the URL-tab control (no render loop, browser-back, garbage-`?tab=`→all), the single-`onNotify`
  announce-confirm, the overlay-correct count, and no regression on the other `AppearanceEditor`/`AppearanceList`
  callers → **zero blockers**, one comment-precision nit (softened). **R2** (a11y/copy/consistency/edges) — no
  blockers → confirmed the decorative-avatar a11y (no double-announce), the pluralized non-alarmist confirm copy,
  the warning-tone weight, the truncate-safe review-tile layout, and the edge cases; applied 2 touch-ups (dropped a
  now-redundant `justify-between`; a decorative-`alt` note) and produced the honest-limits list above.
- **Next:** the owner picks the next Round-3 phase — the recommended order continues **BP25** (floor sweep) →
  BP23/BP24 ([`product/07`](../product/07-improvement-roadmap-round-3.md)), plus the **blocked slice 4** whenever
  the owner re-opens it; a phase starts only on owner pick + scope re-confirm.
