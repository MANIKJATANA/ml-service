# 0064 — Product review, Round 3 (UX-first, all roles) + BP18–BP25 roadmap proposal

- **Date:** 2026-08-03 (review executed 2026-07-28 → 2026-08-03)
- **Status:** accepted (docs-only; no code changed; build track remains paused per [0063](0063-park-remaining-backlog.md))

## Context

The BP1–BP17 build track completed and was parked ([0063](0063-park-remaining-backlog.md)). The owner asked for
a fresh product review **from the UX perspective**: walk the product as each role from a real user's viewpoint
(platform admin, school admin, teacher, student — plus the parent using the student account), layered with a
senior-product-manager analysis from every angle. Round 2's review ([0054](0054-product-review-round-2-and-BP9-roadmap.md),
`product/02`) predates all of BP9–BP17 landing, so Round 3 also had to re-test whether that track actually
closed what Round 2 opened.

Owner scope decisions (asked up front): deliverable = review **+ roadmap proposal** (the `02`+`04` pattern);
**parked items (BP12/BP15/BP16, BP6 video timeline) excluded** — cited in one line where touched, never
re-reported or re-ranked, and the roadmap is built from new findings only; format = markdown docs **+ an HTML
executive summary** (repo-root, untracked-style artifact like the `bp*-plan.html` explainers).

## Decision

Run a **static, code-grounded, multi-agent review** and record it as three artifacts:

1. **`product/06-product-review-round-3-ux.md`** — the review. Method: 12 agents in two batches —
   4 persona walks (first-run + Greenfield scale: 800 students / ~120 events / a 900-photo student), a
   **leads verifier** (25 pre-review rough-edge leads → 10 confirmed / 4 partial / **11 refuted**, incl. four
   invented UI elements — recorded in §7b so no future round re-chases them), an **R2 re-tester** (every claim
   in `product/02` → 32 RESOLVED / 5 PARTIAL / 2 UNRESOLVED / 4 PARKED / 0 REGRESSED), and 6 senior-PM sweeps
   (core-job trace, IA/vocabulary/design-bar, feedback/error matrix, a11y+mobile floor, trust/privacy/
   credential lifecycle, instrumentation honesty). Every finding carries file:line evidence; absence claims
   carry the grep trail; runtime-feel claims are labeled `unverified-runtime` and capped at High. Findings were
   deduped on root cause, severity-calibrated in one sitting (1-Critical-per-agent nomination cap; written
   no-workaround tests), and clustered into **themes J–Q** (continuing R2's A–I).
2. **`product/07-improvement-roadmap-round-3.md`** — the proposal: one phase per theme, **BP18–BP25**, with
   recommended order BP18 → BP19 → BP21 → BP20 → BP22 → BP25 → BP23 → BP24. Nothing scheduled; owner picks.
3. **`product-review-r3.html`** (repo root) — the executive summary; the markdown stands alone.

**Headline results.** Two Criticals: **(J) student credential loss has no recovery path and the only remedy —
delete/recreate — permanently destroys the child's photo history** (BP8e purges matches; the worker skips
completed media on reprocess; nominated independently by three agents, four-door no-workaround test written
out); **(K) a dead-lettered/lost processing job strands an event in "Distribution is running" forever** (no DLQ
consumer, re-enqueue refused, no staleness cue, zero failure metrics). Eighteen Highs — the biggest clusters:
the student **arrival moment is inverted** (oldest-first ordering buries the new photos; the badge is fetched
once per session), the product **misdescribes itself** (seven words for one pipeline; "Only you can see these"
false vs `gallery:view_all`; face recognition explained to no one; the erasure dialog under- and over-tells),
the **review loop is under-armed** (no reference face beside the candidate; review debt invisible while
auto-announce defaults on), and the owner **runs blind** ("Delivery rate" measures the announce button;
accuracy ground truth in `match_corrections` never aggregated; media has no uploader column — a closing
window). R2 re-test verdict: Linear delivered, Stripe substantially closed, **Pinterest half-closed** (grid
mechanics hit the bar; the student still sits in admin chrome); Round 2's scale complaints are structurally gone.

**Verification (the 2× loop, adapted for docs).** Loop 1: three parallel verifiers re-opened every citation and
re-ran every absence grep — ~230 citations checked, ~18 flagged (all wording/bookkeeping-level: line drifts,
two stale counts, four ghost finding-IDs in `07`, wrong HTML severity tallies, and one substantive narrowing —
a mere worker crash self-heals via XAUTOCLAIM, so Critical K is the DLQ/lost-job path); **zero findings
killed**; all fixes applied. Loop 2: a no-context cold-read for severity consistency, scorecard↔body↔theme
agreement, roadmap traceability, HTML↔md agreement, no-parked-rediscovery, and house style.

## Why

- **Static-only** because the FE live smoke + Docker `buffalo_l` runtime remain pending (`product/05` §D) —
  the review says so in §1 and routes its own unverifiable claims to a §7c live-check list rather than
  asserting them.
- **A leads-verifier before the walks** because the pre-review sweep had already demonstrated hallucination
  (four invented UI elements among the refuted); gating every inherited claim on positive evidence kept them
  out of the doc.
- **Parked exclusion** is the owner's call: re-ranking parked work is a scope decision for un-pausing, not a
  review's job. BP12 in particular remains the known biggest gap — deliberately absent here.

## Consequences

- `product/06` + `product/07` + `product-review-r3.html` exist; `product/05` untouched; **no code changed**.
- The next build starts only when the owner picks a phase from `07` (or anything else) and re-confirms scope —
  BP18/BP19 carry the "these are the Criticals" weighting; BP21 is the cheapest High (strings).
- `07` names two optional companions kept out of their parent phases: **BP18b** (session revocation on
  password change + student disable) and **BP20b** (the student-chrome/warm-layout pass).
- CLAUDE.md status paragraph updated in this change.
