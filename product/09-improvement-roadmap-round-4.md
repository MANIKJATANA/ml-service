# Improvement Roadmap — Round 4 (pre-release, staff & school-admin)

**Date:** 2026-08-29
**Source review:** [`product/08-product-review-round-4-staff-admin.md`](08-product-review-round-4-staff-admin.md)
**Framing:** the **last roadmap before the 1st release.** It converts the Round-4 findings into approve-before-build
phases, tiered by *release-criticality* — what **blocks** a confident release, what makes it **school-ready** vs.
merely demo-ready, and what is **post-release polish.** Per the working rule, **this schedules nothing** — a phase
starts only on owner pick + scope re-confirm, after a plan + HTML explainer verified before code.

**Numbering:** phases continue at **BP26** (BP25 was the last shipped). Where a phase delivers a previously-**parked**
item, it says so — e.g. BP26 delivers the parked **BP12**. Parked **BP15/BP16** and the **BP6 video timeline** stay
parked; the **blocked BP22 slice 4** stays blocked (see `product/05`).

---

> **⚠ v1 pivot (owner decision, 2026-08-29).** **No student login in v1** — students don't access the app.
> Distribution is **staff-mediated**: a teacher/admin **downloads a student's photos and shares them (WhatsApp)**.
> So the Tier-0 "release blocker" changes shape entirely: it is **no longer outbound email** (that — the original
> BP26 — folds into the **parked BP12**, deferred post-v1) but a **small, FE-only** feature — **staff per-student
> "Download all"** — which is the reframed **BP26** below. The in-app announce/"opened" path and the whole student
> surface are **dormant in v1** (shipped, unused; an optional "v1 hygiene" cleanup is noted under Still parked). Net
> effect: **the release blocker got much cheaper** (Low, FE-only) — good news for the timeline.

---

## The one-screen picture

```
TIER 0 — v1 DISTRIBUTION (the release mechanism · small · FE-only)
  BP26  Staff download & share ............... per-student "Download all" for teacher + admin → share via WhatsApp

TIER 1 — SCHOOL-READY (strongly recommended before release)
  BP27  Bulk operations parity ................. off-board / recover / invite at 800-student scale
  BP28  Governance & audit completeness ........ log filters + export + admin-action trail
  BP29  Teacher-role coherence ................. the second persona, finished

TIER 2 — RAISES THE BAR (recommended; can trail the release)
  BP30  Review-loop power tools ................ table view · threshold-select · discoverable undo
  BP31  Onboarding feedback loop & copy polish . momentum · deep-links · a dozen small truths

STILL PARKED (call out, don't schedule)
  BP12  Outbound email/SMS to students ....... the ORIGINAL BP26 scope — deferred post-v1 (no student login in v1)
  BP16  Lifecycle & retention ................ event hard-delete · erasure undo · data export
  BP15  Accuracy at scale .................... enrollment staleness · per-event reconciliation
  BP6   Video timeline / BP22-s4 ............. per §product/05
```

**Minimum viable release (recommendation):** **BP26 + BP27 + BP28.** BP26 (staff per-student download → WhatsApp)
makes v1 distribution actually work; bulk parity and governance make a real school able to run and be accountable.
**BP29** is close behind (the teacher is half the staff base). **BP30/BP31** are genuinely optional for launch. Post
the v1 pivot, **BP26 is now small + FE-only** — the release blocker got cheap.

---

## TIER 0 — v1 distribution (the release mechanism)

### BP26 — Staff download & share  *(the v1 distribution build; outbound email → parked BP12)*

**Problem (R4-D00, reframed for the v1 pivot).** v1 has **no student login** — students don't open the app, so there
is nothing to announce *to* and no inbox to email. Delivery is **staff-mediated**: a teacher/admin downloads a
student's photos and shares them (WhatsApp). The blocker is that **staff have no per-student "download all"** — today
they can grab a single photo or an event's whole gallery, but not **"every photo of student X across all their
events"** in one zip. That per-student bundle is the exact thing a student could already do for *themselves*
(`(student)/me` "Download all", BP20); v1 needs the **staff-side** equivalent.

**Scope (small, FE-only).**
1. **A "Download all N photos" action on the student detail** (`students/[studentId]`, in the "Appears in" area) —
   feeds the student's full effective media list into the existing `useDownloadAll` streaming zip, foldered/named by
   event/date (`{Event}/{date}-nnn.jpg` inside `{Student-Name}-photos-{date}.zip`), reusing the student self-view's
   `entryBase`/`sanitizeFilename` pattern verbatim. Available to **teacher *and* school-admin** (both already hold
   `gallery:view_all`; the download entitlement is reused, never widened).
2. **(Optional, cheap) a per-student download on the gallery "By student" tab** — "Download {student}'s photos" for the
   picked student in that one event (uses the already-fetched `event_student_media` ids).
3. **Honest states, reused (BP24b):** partial → "Saved N of M"; a non-streaming browser → "first 500…"; a cancel →
   silent; **a photoless / no-matched student → the button is hidden** ("No photos yet").

**Surfaces.** **FE only.** Reuses `GET /students/{id}/media` (staff-entitled, BP5 effective overlay — rejected
excluded, added included) + `GET /students/{id}/events` (names/dates for foldering) + `useDownloadAll` +
`GET /media/{id}/download` (staff mint). **No backend, ML, migration, permission, or dependency change.**

**Effort:** **Low** (FE-only, composes shipped primitives). One slice.

**Honest limits (documented).** Non-streaming browsers (Firefox/Safari) cap a single zip at 500 photos (the existing
BP9 limit) — a >500-photo student there gets the first 500 + a "use Chrome/Edge or download per-event" note (rare per
single student). "All photos" = the student's **effective** appearances (a photo still `needs_review` is included —
staff decide, same as the student would have received). The zip is built client-side from N per-photo signed URLs
(bounded memory on Chrome/Edge; buffered elsewhere).

**Deferred to post-v1 (parked BP12):** outbound **email/SMS** to students + a tokenized share link on the
`CompositeNotifier` seam — not needed while there is no student login and staff share manually. If a later pilot wants
a lightweight nudge, the cheap first step is a **"not-opened / matched-student CSV export"** for manual mail-merge.

---

## TIER 1 — School-ready (strongly recommended)

### BP27 — Bulk operations parity

**Problem.** Every bulk affordance stops one step short of the scale the product targets (800 students / 25 classes /
20 teachers). The one-at-a-time cliffs: **R4-A04** (no bulk delete/disable), **R4-A05** (no cohort credential resend),
**R4-A13** (no bulk staff invite), **R4-A07** (bulk-photo enroll lacks retry-failed + overwrite confirm),
**R4-A06** (select-all is loaded-page-only), **R4-A10** (no bulk-remove-from-class).

**Scope.**
- **Students:** a stale-safe multi-select bar → **bulk disable/enable**, **bulk resend credentials** (loops BP18a's
  single resend; shown-once credentials batched like BP7d), **bulk delete/erasure** (loops BP8e with a strong
  confirm), **bulk remove-from-class**.
- **Select-all-N-matching:** an opt-in "select all N that match this filter" (an id-scan like BP9's global count-sort,
  tenant-scoped) so bulk actions can span pages, not just the loaded one.
- **Staff:** a **CSV bulk invite** mirroring the student importer (server-gen temp passwords, shown-once,
  download-credentials).
- **Bulk-photo dialog:** a **retry-failed** (reuse BP19d's kept-handles pattern) + an **overwrite confirm / keep-
  existing** option.

**Surfaces.** Backend (batch endpoints looping the *existing, tested* single-writes — no new domain logic;
select-all-matching id-scan); FE (multi-select bars + a staff importer). **ML/Migration:** none.
**Effort:** **Medium** (mostly composition over shipped primitives). Sliceable by object (students → staff →
bulk-photo). **Closes:** R4-A04/05/06/07/10/13.
**Honest limits.** Best-effort batch loops (per-row results, never abort-the-batch — the BP7d contract); a set-based
bulk write is the scale-up. Bulk erasure is irreversible (same as single).

### BP28 — Governance & audit completeness

**Problem.** The access log answers half its question and there is **no admin-action trail.** **R4-A24** (no filter UI,
though backend event/student filters are *already wired* — BP8b/BP23), **R4-A25** (disable/delete/re-enroll/re-invite
are unrecorded), **R4-A26** (no CSV export). For a product handling minors' photos, an actor trail on governance
actions is table-stakes for school procurement.

**Scope.**
- **Surface the wired audit filters** — actor/student/event/date-range controls on the access-log page (the backend
  already supports event/student; add date-range + a light actor filter). **Low effort, high trust payoff.**
- **CSV export** of the (filtered) log.
- **An admin-action audit** — an append-only record of governance actions (student/teacher disable·enable·delete·
  re-enroll·re-invite·resend), mirroring the BP8b `download_audit` structure (VO + repo port + postgres adapter +
  read service). Surfaced to school-admins as a second audit tab. **Migration:** one new table (like `0010`).
- **(Optional, cheap) teacher cap visibility** school-side — annotate the staff list "at capacity" instead of a
  post-submit 409 (R4-A15 / R3-A2-04).

**Surfaces.** Backend (filters wiring + a new audit table/service); FE (filter UI + export + a governance-log view).
**ML:** none. **Effort:** **Medium** (the filters are Low; the admin-action audit is the Medium half — new table +
write-hooks on the governance mutations). Sliceable: **28a** filters+export (no migration) → **28b** admin-action
audit (one migration). **Closes:** R4-A24/25/26 (+ A15).
**Honest limits.** The admin-action audit records forward-only from launch (no backfill, like BP23's `last_login_at`);
it captures *staff/admin* governance actions, not every read.

### BP29 — Teacher-role coherence

**Problem.** The teacher is a capable daily-driver but the role reads as half-built: **R4-T01** (un-delegated teacher
sees everything, unexplained — Round-3 R3-A3-04, still open), **R4-T02** (the checklist dead-ends a teacher on "Add a
teacher"), **R4-T03** (no read-only class roster for a delegated teacher), **R4-T04** (no "what's mine" lens),
**R4-T05/T06** (class dropdown doesn't mark "mine"; scope goes stale), **R4-T07/T08** (silent RoleGate redirect;
pre-distribution checklist noise).

**Scope.**
- **Role-aware onboarding:** hide admin-only checklist steps for a teacher; give a teacher a short "your role" first-run
  note (what a teacher can do) instead of the admin setup steps (fixes R4-T02, R4-T08).
- **Delegation clarity:** when an un-delegated teacher lands on the full school list, a dismissible banner — "You're
  seeing all classes. Ask your admin to assign you classes to focus your lists." — and, in the class dropdown, mark
  the teacher's delegated classes (fixes R4-T01, R4-T05). Refresh `my-classes` on focus/interval so live delegation
  isn't stale (R4-T06).
- **Read-only class roster for teachers:** let a delegated teacher open *their* class's roster (read-only — no
  `class:manage`), closing the "manage the events but can't see the class" asymmetry (R4-T03).
- **A "My work" lens (optional):** a teacher dashboard section — my events needing action / my recent uploads / my
  pending reviews — the "what's mine to do" view (R4-T04).
- **Graceful denial:** RoleGate shows a brief "not available for your role" instead of a silent bounce (R4-T07).

**Surfaces.** Mostly **FE** (gating, banners, a read-only roster view, a dashboard lens); a possible small backend read
for "my class roster" if the existing student-list-by-class filter isn't enough (it likely is). **ML/Migration:**
none. **Effort:** **Medium** (FE-weighted). **Closes:** R4-T01–T08.
**Honest limits.** Delegation stays *convenience-scope*, not a security boundary (BP11c's owner call — a teacher could
already see the whole school); this phase makes that *legible*, it doesn't restrict.

---

## TIER 2 — Raises the bar (recommended; can trail release)

### BP30 — Review-loop power tools at scale

**Problem.** The review lane is correct but lacks power tools at 200-ambiguous-match volume: **R4-A20** (batch-undo is
undiscoverable; no "show hidden/rejected matches"), **R4-A21** (no confidence-threshold *select*), **R4-A22**
(grid-only, no per-tile context), **R4-A23** (add-students search has no pagination feedback), **R4-F04** (lightbox
doesn't auto-page at its end).

**Scope.** A **threshold multi-select** ("select all below N%") that stages verdicts without auto-applying (honoring
BP22's no-auto-*confirm* stance); a discoverable **Undo** after batch reject (a transient control) + a **"show
hidden/rejected"** gallery filter for spot-checks; an optional **table view** toggle for the review lane; a
**"showing X of Y / type to refine"** cue in the add-students popover; **lightbox auto-paging** at its end.
**Surfaces.** FE-only (composes shipped BP13/BP22 primitives). **ML/Migration/dep:** none. **Effort:** **Medium**.
**Closes:** R4-A20/21/22/23, R4-F04.
**Honest limits.** Still **no auto-confirm** (deliberate); threshold-select stages, the human commits.

### BP31 — Onboarding feedback loop & copy/discoverability polish

**Problem.** A grab-bag of momentum + truthfulness fixes, each individually small: **R4-A01** (checklist has no
completion feedback loop), **R4-F02** (the "to match" alert doesn't deep-link to the event's Process), **R4-F01**
(no inline "Fix now" in the failure note), **R4-A08** (photo-field doesn't say it enrolls a face), **R4-A09** (import
results hide the server-reject reason), **R4-A18** (no live-sync cue during matching), **R4-A19** (category hint +
clearer "clear tag" wording), **R4-A02** (dashboard warmth), **R4-A11/A14** (class grade/section display; edit-classes
search), **R4-F05** (partial-download failures unnamed).

**Scope.** Return-to-checklist momentum after each step; deep-link dashboard alerts to the exact action; inline
"Replace photo" inside the EnrollmentFailureNote; surface the import server-reject `reason`; a subtle live-sync badge
during polling; the reference-photo + category + clear-tag copy fixes; a couple of display cleanups.
**Surfaces.** FE-only (plus surfacing an already-returned `reason`). **ML/Migration/dep:** none. **Effort:** **Low–
Medium** (a batch of small, independent fixes — ideal "floor-sweep 2" companion). **Closes:** R4-A01/02/08/09/11/14/18/
19, R4-F01/F02/F05.

---

## Still parked (called out, not scheduled)

- **BP12 — Outbound email/SMS (the original BP26 scope).** Deliver photos to a student's own inbox + a tokenized share
  link on the `CompositeNotifier` seam. **Deferred post-v1** — with no student login and staff sharing manually
  (WhatsApp), there is no inbox to reach and no in-app "opened" signal to drive. Revisit if a later release
  re-introduces student accounts or wants an automated nudge.
- **v1 hygiene (optional companion, not scheduled).** Because v1 has no student login, some shipped flows are now dead
  weight: create-student + bulk-import still hand out a **shown-once student temp password** (a login nobody uses), and
  the **student `(student)/me` surface** + BP18/BP20/BP22-student paths still exist unused. A light cleanup — hide the
  student-password step, hide the student surface from the build — would de-clutter v1 without ripping out code. Say
  the word to scope it; leaving it untouched is harmless (just unused).
- **BP16 — Lifecycle & retention.** Event **hard-delete** (purge media rows + storage objects + matches/detections,
  reusing BP8e's erasure machinery), an **erasure undo/grace window**, and **data-export-before-delete** (GDPR-style)
  — the home for **R4-F03**. Still lowest urgency (archive covers the common case); becomes relevant once schools
  accumulate stale events. *Pure risk-reduction.*
- **BP15 — Accuracy at scale.** Enrollment **staleness** signal + re-enroll prompt, and per-event **reconciliation**
  ("18 of 22 enrolled students found — who's missing?") — the trust tool that also feeds the analytics context gap
  (R4-A03). Cohort-scoped *matching* stays dropped (no ML change). Medium effort; genuinely useful for staff trust —
  a candidate for **just after** the release tier if accuracy questions surface in the pilot.
- **BP6 video timeline** and **BP22 slice 4** (student "This isn't me" staff-visibility) — unchanged from
  `product/05`; owner-parked / blocked.

---

## Recommended sequence & rationale

1. **Build BP26 first — it's now cheap.** The v1 distribution mechanism is a small **FE-only** staff per-student
   download (reuses `useDownloadAll`); no provider/secrets/link-type decision remains (outbound email is parked to
   BP12). It unblocks the release identity in a few FE days.
2. **BP27 → BP28** — make the school able to *operate* (off-board, recover, invite in bulk) and *account* (audit).
   These are what a procurement/IT reviewer checks.
3. **BP29** — finish the teacher before real teachers arrive; it's FE-weighted and low-risk.
4. **BP30 / BP31** — schedule into the release only if time allows; both are safe to trail as a fast-follow.

**Effort ladder (rough):** BP26 **Low (FE-only)** · BP27 Medium · BP28 Medium · BP29 Medium · BP30 Medium ·
BP31 Low–Medium. Post the v1 pivot, **every phase except BP28-b is no-migration / no-ML / no-new-dep**, composing
shipped primitives — so the whole tier is cheap; the one heavy investment (outbound email) is parked to BP12 post-v1.

---

## Working agreement (unchanged)

For each chosen phase: **plan → HTML explainer verified before code → slice-by-slice implement → full gate (BE
ruff+mypy+pytest+layering; FE lint+tsc+build) → 2× review→fix loop (R1 correctness, R2 edge/a11y/copy) → decision doc
+ README + CLAUDE.md → STOP for review.** Migrations on a **throwaway** DB only; new env vars in `.env.example`; commit
only on explicit ask. **Nothing here is scheduled — pick a phase and re-confirm scope to begin.**
