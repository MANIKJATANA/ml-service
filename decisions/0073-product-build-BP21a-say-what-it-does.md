# 0073 — Product Build BP21a: Say what it does (the copy + explainer pass)

- **Date:** 2026-08-16
- **Status:** implemented (gate green; awaiting owner review before commit)
- **Phase:** the first slice of **BP21 (Say what it does)** — Round-3 review theme **M**
  ([0064](0064-product-review-round-3-ux.md), [`product/06`](../product/06-product-review-round-3-ux.md)),
  sliced **a** (this, all copy/UX) + **b** (error truthfulness, next). **FE-only — no backend/ML change, no
  migration, no new dependency, no new permission.**

## Context

The product described itself *from the system's side*, in **seven different words for two pipelines**, and made a
few claims that were outright false:

- **One overloaded vocabulary.** The ML face-matching step was "Process photos"/"Redistribute" (buttons) but
  "Distribution started." (toast) and "Processing" (status pill); telling students was "Notify"/"Auto-announce"/
  "Notified" — while the dashboard checklist said "Distribute to students", analytics "Delivery rate", the estate
  column "Distributed". The word **"Distribution" meant *both*** — so an admin could click "Process photos", read
  "Distribution started.", and reasonably believe students had been told (they hadn't — that's the separate Notify).
- **False / unexplained claims.** Face recognition was explained to **no one** (students triggered "This isn't me"
  against a system never named; staff corrected a confidence % nobody defined); the student privacy line risked
  reading as "only you can see these" (false — staff have `gallery:view_all`); the erasure dialog **under- and
  over-told** (silent on the purged match history *and* on the surviving event photos); the audit page **overclaimed**
  ("Every photo download") yet **under-disclosed** to teachers (their downloads are recorded, undisclosed); a
  photoless student read "Pending" instead of "No photo yet"; and a few small naming/scope gaps (the browser tab
  title, a stale "(soon)", a silent 30 MB limit).

Owner decisions (via the approved plan + `bp21-plan.html`): **one grammar = Match / Announce**; **2 sub-phases**
(21a copy/UX, 21b errors); include the error slice. This is 21a.

## Decision

Everything below is user-facing string / small-JSX work in `frontend/` only. Internal identifiers were deliberately
**left unchanged** (not user-facing): `processing_status` / `EventProcessingStatus` values + types, the
`DistributionCard` component name, `events_undistributed` / `has_distributed` / `events_distributed` fields, the
`processEvent` / `notifyStudents` / `onProcess` / `onNotify` functions.

1. **One grammar — Match / Announce.** Swept every surface:
   - **Match** (the ML step): `PROCESSING_LABEL` (`lib/events/status.ts`) Processing→**Matching**, Completed→**Matched**,
     failed→**Matching failed** — the single source for the match pills (used by the event detail *and* list via
     `derivePillStatus`). Event detail: "Process photos"/"Redistribute"→**Match photos / Match again**, toast→
     **"Matching started."**, progress label + counts→**matched**, "Processing since"→**Matching since**, the failure
     note reworded to the matching service. Events-list column→**Matching**. Dashboard alerts→**"…photos to match"**,
     **"matching now"**, hint **"awaiting matching"** / **"All matched"**.
   - **Announce** (telling students): the DistributionCard `<h2>`→**Announce**, "Notify students"→**Announce to
     students** / **Announce again**, "Notified N"→**Announced to N**, auto-toggle→"when matching finishes"; the
     dashboard checklist step→**Announce to students**; analytics→**Announce rate** / **Announced**
     (`program-analytics.tsx`, `rate-card.tsx` doc example); estate column→**Announced** (`estate/page.tsx`).
   - The several "run distribution" prose descriptions (create-event dialog, events header + empty state, gallery
     empty state, upload page) → **"match and announce"** / **"Match this event's photos"** phrasings.
   - Browser tab title (`app/layout.tsx`) "Photo Distribution"→**"Photos"** (matching the shell brand + the student
     "My Photos" nav, which the page `<h1>` now also matches).
2. **Announce honesty.** The notify toast → **"Announced to N students — they'll see it in My Photos."**; the
   DistributionCard surfaces **"in-app only for now"** and its roster reads **"Announced to N students · X opened"**
   (pluralized). No new string implies an outbound email/text (outbound is parked BP12).
3. **True privacy scope.** The student `me/events` hero + empty state + the explainer say a student sees only photos
   they're in, **private to them and their school's staff**, and other students only see a photo if they're in it too
   — never "only you".
4. **"How photo matching works" explainer + confidence legend.** A new static page at **`app/(help)/how-matching-works/`**
   (a `(help)` route group with an all-roles `AuthGuard`) — plain-language: what face matching does, how a reference
   photo is used, **what a confidence % means**, why "This isn't me" exists, who can see what. Linked from the student
   hero + empty state and from the staff review lane; a one-line **confidence legend** ("Percentages are how sure the
   match is — a low one is worth a second look") sits in both `appearance-editor.tsx` (staff) and `appearance-list.tsx`
   (read-only), each gated by a `hasConfidence` guard so a null-confidence (all-"Added") photo shows just the link.
5. **Erasure dialog, both sides.** The delete-student `ConfirmDialog` now tells both: it destroys the login /
   profile / face enrollment / **matched-photo history** (unrecoverable), **and** the event photos stay in every
   gallery + past download records are kept but anonymized (accurate to BP8e, [0053](0053-product-build-BP8e-student-erasure.md)).
6. **Audit honesty.** The access-log caption says it **records in-app saves, not views or a right-click save**; the
   `DownloadHistory` panel now shows teachers a one-line **"Downloads are recorded and visible to your school's
   admins"** (accurate to BP8b, [0050](0050-product-build-BP8b-download-audit.md): the `POST` download records; the
   view mint records nothing; `audit:view` is admin-only, but teachers' downloads *are* recorded).
7. **Naming / scope tidy-ups.** A shared **`enrollDisplay`** (`lib/students/enrollment.ts`) shows **"No photo yet"**
   (neutral) for a photoless+`pending` student instead of the enrollment "Pending" pill (list + detail); the schools
   **list** status pill reads **"Active"/"Suspended"** (matching the detail, not the raw enum); the stale class-dialog
   **"(soon)"** dropped (delegation shipped in BP11c); the event uploader hint states **"up to 30 MB each"** (the only
   video surface, previously silent).

## Why

- **Two verbs, not seven.** "Match" and "Announce" are the two things the product actually does; naming them
  consistently everywhere is what lets an admin predict what a button will do. The overloaded "Distribution" was the
  specific cause of the "I clicked process, did students get told?" confusion.
- **Explain the system that asks users to judge it.** Students are asked "Is this you?" and staff correct a
  confidence %; both deserve one plain-language page and an inline legend rather than an unexplained number.
- **Say what's true, no more.** Each honesty fix was checked against how the system actually behaves (privacy vs
  `gallery:view_all`; erasure vs BP8e; audit vs BP8b; in-app-only vs the `log` notification channel) — the review
  loop verified every claim.
- **Labels are FE-side.** The backend enums / fields carry no user copy, so the whole sweep is frontend strings +
  one new static page — low-risk, no migration, no service change.

## Consequences / honest limits (documented)

- **FE-only; no backend/ML/migration/dependency/permission change.** `git status` shows only `frontend/` modified
  (plus the intentionally-untracked `bp21-plan.html`).
- **Internal names still say "Distribution"/"Process"/"Notify"** (component/function/field/enum identifiers) — the
  sweep is deliberately user-facing copy only; renaming code identifiers is churn with no user benefit and risks a
  backend-contract touch. The `processing_status` enum *values* are the backend contract and are untouched.
- **Outbound is still not built** ("in-app only for now" is the honest caveat; email/whatsapp is parked BP12). The
  Announce copy never implies a message left the app.
- **The `(help)` page is one shared route** reachable by any signed-in role via its all-roles guard; it renders inside
  the role-aware `AppShell` (like every other group layout). Route groups don't affect the URL, so every
  `/how-matching-works` link resolves to it.
- **Error truthfulness is BP21b** (the mid-session 401 → dead Retry, 422 → "Unprocessable Entity", stripped
  `Retry-After` on a 429, raw 500 `str(exc)`) — real FE/BFF plumbing, the next slice.
- Verified: FE **lint + tsc + `next build` green** (`/how-matching-works` prerenders as static); no BE/ML suite delta.
  **2× review→fix loop — no blockers.** **R1** (correctness/completeness): rename-completeness (no user-facing
  "Distribution" leftover), route/link/guard correctness, `enrollDisplay` conditional, the confidence-legend logic,
  and every honesty claim vs 0050/0053 all verified clean → **1 fix**: an audit column header that no longer matched
  its cell. **R2** (copy quality / a11y / consistency / honest limits): the explainer, the a11y of the new links +
  legend + teacher disclosure, the null-confidence edge case, and cross-surface vocabulary consistency all confirmed
  clean → **3 small fixes**: pluralized the "Announced to N students · X opened" roster (was bare at N=1), the audit
  header "Self-download by"→**"Student (self)"** (clearer over mostly-blank cells), tightened the audit description,
  and a warmer re-enroll-failure toast that points at the failure note. The verbose erasure dialog was kept as-is
  (accuracy over brevity for a destructive, irreversible action).
- **Next:** **BP21b** (error truthfulness), then the owner picks the next Round-3 phase (recommended: BP20 → …,
  [`product/07`](../product/07-improvement-roadmap-round-3.md)).
