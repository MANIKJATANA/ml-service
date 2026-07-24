# 0054 — Product review Round 2 (per-role, at scale) + the BP9–BP17 roadmap

**Date:** 2026-07-25
**Status:** Accepted (docs-only; no code, no migration, no service change)

## Context

BP1–BP8 are complete — the product is "feature-complete + hardened," and `03-improvement-roadmap.md`
declared the roadmap done. But two things were never tested:

1. **Scale.** Round 1's screens were designed and demoed at 3–20 rows. Nobody had walked the app as a real
   school — ~800 students across grades, ~120 events/year, a 3rd-year student with ~900 photos.
2. **A written review.** `00`/`01` both referenced `02-product-review.md` as the file that "scores one
   against the other," but it was **never written** — Round 1 was built from the `00`/`01`/`03` triad
   directly.

The owner asked for a **second-round product review** focused on **feature + UX (not tech)**, seen **as a
user** at 100+ events / hundreds of students, and — in follow-up — **per role** ("how we'd like to see the
application based on his/her role"). Prioritization was again delegated to the product specialist.

A code exploration (backend list/gallery endpoints, frontend list/gallery components, the product docs)
grounded the findings: only `/audit/downloads` paginates; the other ~11 list/gallery endpoints return
unbounded full sets; `GalleryService` loads the whole school roster/event list into Python and filters
in-memory; FE search/sort/filter is client-side over already-fetched rows; there is no class/section on
students, no term/category on events; every event is matched against the whole-school FAISS index; and the
parent/guardian — the real recipient for a young child — is not modelled anywhere.

## Decision

**Write the missing `product/02-product-review.md` as the Round-2 review, and open a `BP9–BP17` track in
its own file, `product/04-improvement-roadmap-round-2.md` (the Round-2 sibling of `03`).** Docs only — each
BP9+ phase is a separate future slice built on explicit approval, per repo convention.

- **`02-product-review.md` (new):** a review walked **per role** (platform admin, school admin, teacher,
  student, and the *missing* parent/guardian) at "Greenfield School" scale. Every finding cites a rubric
  lens ID (`01` §3), a severity (Critical/High/Medium/Low), and a **gap type** (display vs capability), and
  is grounded in a real file/line (§5 of the doc). Nine cross-cutting **themes A–I** generate the role
  findings. The three Critical, capability-level gaps: **A** the enrollment wall (a big school can't be
  turned on — CSV makes photoless students, faces are added one-at-a-time), **C** distribution reach (in-app
  only; no email/push, no parent recipient), **B** no organizing structure (flat 800-row/120-event world;
  also causes whole-school matching noise + leakage).
- **`04-improvement-roadmap-round-2.md` (new file):** BP9–BP17 in `03`'s phase format, with a Round-2
  effort×impact map + an explicit build order. **Recommended build order (owner-delegated):** **BP9**
  scale-ready lists/galleries (theme D — the low-risk, mostly query-only substrate) + **BP17** image
  thumbnails/derivatives (the fast-UI pair) → **BP10** bulk photo enrollment (A, the switch-on) → **BP11**
  class/term structure (B) → **BP13** bulk actions & batch review (E) → **BP14** program analytics/trends
  (G) — **then the three deprioritised phases** (owner calls, 2026-07-25): **BP12** distribution reach
  (email **to the student account** + share link — no guardian model, C), **BP15** accuracy at scale
  (staleness + reconciliation, H), and **BP16** lifecycle & retention (event hard-delete reusing BP8e's
  machinery, I). They keep their IDs but sit at the back.
- **`00` touched:** the "BP1–BP8 roadmap complete" framing now reads "complete (Round 1)" and points at the
  BP9+ track; the previously-deferred event hard-delete + retention are folded into **BP16**.
- **Owner refinements (same day, 2026-07-25):** (1) parent/guardian is **not** a separate role — the parent
  uses the **student account** (its email is theirs), so **BP12** drops the guardian model (email to the
  student account + share link); (2) **cohort-scoped matching** is **skipped for now** — **BP15** keeps only
  enrollment staleness + per-event reconciliation; (3) added **BP17** image thumbnails/derivatives (the
  fast-UI companion to BP9, incl. the student-list avatar with a thumbnail-or-full-res fallback); (4) **BP16**
  (lifecycle & retention) also **deprioritised to the back** — pure risk-reduction, the lowest product urgency.

## Why

- **Docs-first, per repo convention.** The review + roadmap are the durable product record; a future session
  can pick up BP9 without re-deriving the priority. Writing `02` also closes a real gap — `00`/`01` cited a
  file that didn't exist.
- **Grounded, not vibes.** Every scale claim ties to a file/line, so the review is falsifiable and the
  effort estimates (display vs capability) are honest.
- **Sequencing rationale.** Lead with the broad, low-risk **substrate** (BP9) because it fixes the felt lag
  *now* (a photoless CSV import already yields 800-row lists) and every later phase's new views depend on
  pagination/server-search; then the **switch-on unblocker** (BP10), since enrollment gates all value; then
  the **structural** gap (BP11) and the remaining M-effort wins. The two **L-effort flagships** — **BP12**
  distribution and **BP15** accuracy — are **deprioritised to the back** (owner call): highest impact but the
  heaviest (net-new email/ML infra), so the cheaper high-value phases land first. This mirrors `03` §1's
  original thesis (cheap high-visibility wins first, then the expensive capabilities).

## Alternatives considered

- **Fold the review into `03` only (skip `02`).** Rejected: `00`/`01` already reference `02` as the scoring
  doc; the per-role review is substantial and deserves its own home, keeping `03` a lean sequenced backlog.
- **Jump straight to building BP9/BP10.** Rejected: the owner asked for a *review*; and repo convention is
  docs-first + stop-for-approval per phase. The build is a separate, approved step.
- **Treat scale purely as a tech/perf issue.** Rejected: the owner explicitly wanted feature/UX from the
  user's side. The performance findings (theme D) are framed as *felt experience* (slow lists, janky
  galleries, OOM download-all), and the sharper gaps (A/B/C) are product-capability, not perf.

## Consequences

- No behavior change now. `product/02-product-review.md` exists; the **BP9–BP17** track lives in
  `product/04-improvement-roadmap-round-2.md` (BP12 + BP15 + BP16 deprioritised to the back); `00`'s completion
  note points forward. BP9 is the recommended next build (`04` §4), pending owner approval, and will land as
  its own `decisions/00NN` entry with the standard gate + 2× review loop.
