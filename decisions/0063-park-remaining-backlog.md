# 0063 — Park the remaining backlog (incl. the BP6 video timeline)

**Date:** 2026-07-27
**Status:** Accepted

## Context

Both recommended tracks are complete: **BP1–BP8** ([`03`](../product/03-improvement-roadmap.md)) and the
**BP9–BP14 + BP17** recommended Round-2 track ([`04`](../product/04-improvement-roadmap-round-2.md)) have all
landed. What remained was the three deprioritised Round-2 phases (BP12/BP15/BP16, already at the back of the
queue by owner call) plus one concrete deferred feature — the **BP6 video "timeline"** (who appears when,
per-timestamp; deferred in [0043](0043-product-build-BP6-video-end-to-end.md)).

The owner asked (2026-07-27): **park the BP6 timeline too**, and keep an explicit **record of everything
skipped** so it's visible at a glance rather than re-derived from the roadmaps + decisions.

## Decision

- **Park the BP6 video timeline** alongside the already-deprioritised BP12/BP15/BP16. Nothing on the product
  backlog is scheduled; each parked item is picked up **only on an explicit owner request**, with a scope
  re-confirm at that time.
- **Establish a single tracker** — [`product/05-parked-backlog.md`](../product/05-parked-backlog.md) — that
  lists every consciously parked/skipped item in one place: the parked phases (BP12/BP15/BP16, incl.
  event-hard-delete + retention folding into BP16), the parked feature (BP6 timeline), the documented
  scale-up/polish refinements (offset→keyset, analytics snapshot table, async thumbnails, sliding-window
  rate-limit + nonce CSP, FAISS lease auto-extension, OTel, FE polish), and the pending live-smoke/Docker
  verification. The tracker is the source of truth for "what's parked"; when an item is built it's removed
  there and ticked in its home roadmap, and any new deferral is added there in the same change.

## Why

- The remaining work is either infra-heavy (BP12), lower-urgency risk-reduction (BP16), lighter accuracy
  tooling (BP15), or a single isolated read (BP6 timeline) — none is currently worth starting, and the owner
  has explicitly parked all of it.
- A dedicated tracker beats scattering "deferred" notes across a dozen decisions: one file answers "what did we
  skip and why", so a future instance doesn't rebuild that picture from scratch.

## Consequences

- **No code change.** Docs only: `product/05-parked-backlog.md` (new), a stale BP11 header in `04` corrected to
  ✅ landed (BP11c had landed), and pointers added from `04` / `README` / `CLAUDE.md`.
- The product build track is **paused** — the next build starts only when the owner picks a parked item (or a
  new one) and re-confirms scope.
