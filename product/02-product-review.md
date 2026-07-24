# 02 — Product Review, Round 2: the experience per role, at scale

> **This file = "how the product actually feels, judged against the bar."** It scores the current state
> (`00-knowledge-base.md`) against the targets/lenses (`01-product-skills-and-rubric.md`) and hands the
> findings to the roadmap — `03-improvement-roadmap.md` (BP1–BP8) and its Round-2 sibling
> `04-improvement-roadmap-round-2.md` (which sequences the fixes — the **BP9+** track).
>
> `00`/`01` referenced this file from the start; **Round 1** (BP1–BP8) was built without it, from the
> `00`/`01`/`03` triad directly. This is the **first written review**, and it is deliberately a *second
> round*: it does the two things Round 1's screens were never stress-tested for.
>
> 1. **Scale.** Round 1 was designed and demoed at 3–20 rows. This review walks the app at **real-school
>    scale** — a school with ~800 students across grades, ~120 events/year, and a 3rd-year student who
>    appears in ~900 photos across ~60 events ("**Greenfield School**", the running scenario).
> 2. **Per role, from their side.** It walks the product as each persona would actually run their part of
>    it — platform admin, school admin, teacher, student, and the **role we never modelled**, the
>    parent/guardian — and asks: *is this how this person would want to see and operate their job?*
>
> **Scope note (unchanged):** this judges the product *as a product*, not the pixels. Consent/legal stays
> out of scope (owned by legal via contracts); privacy appears only as *product trust* (`01` §2).
>
> _Snapshot: 2026-07-25 · All three services v1 feature-complete + hardened; BP1–BP8 landed. Findings here
> open the **BP9–BP17** track in its own file, `04-improvement-roadmap-round-2.md`._

---

## 1. How to read this review

- **Method.** For each role, walk their journey (`00` §5) at Greenfield scale, then for each capability/
  screen compare the current state (`00`) to the target (`01` §5). Every finding cites a **lens ID**
  (`01` §3: D1–D8 design · P1–P10 UX · X1–X6 domain), a **severity**, and a **gap type**.
- **Severity.** **Critical** = blocks the core value (the product can't do its job at scale) · **High** =
  a role's primary job is painful or degraded · **Medium** = friction, workaround exists · **Low** = polish.
- **Gap type** (from `03` §1). **Display gap** = the data already flows, the product just doesn't *show*
  it — cheap (query-only backend + FE). **Capability gap** = the capability doesn't exist end-to-end —
  expensive (net-new backend/ML/infra). Naming the type up front is what makes the roadmap honest about cost.
- **Grounding.** Every scale claim is tied to a real file/line (§5). This is a review, not a vibe — if a
  screen loads the whole school into memory, we say where.

---

## 2. Scorecard — the estate at a glance (Stripe-grade summary)

| Role | Job holds up at demo scale? | Breaks at Greenfield scale | Worst finding | Lens |
|---|---|---|---|---|
| **platform_admin** | ✅ estate list + rollups | ⚠️ blind to *adoption* — a stuck school looks like a thriving one | no cross-school health / funnel | T4/P1/X4 |
| **school_admin** | ✅ command center + rich lists | ⛔ **can't switch the school on** (enrollment wall); flat 800-row world | **bulk photo enrollment absent** | X4/T8/P5 |
| **teacher** | ✅ event→upload→process→triage | ⛔ one-at-a-time review; not "my" events; gallery lag | **no batch review** | X2/P5 |
| **student** | ✅ Pinterest gallery + new-photos signal | ⛔ 60-chip / 900-photo firehose; **photos never *arrive*** | **no real delivery** (in-app only) | X1/P5/P9 |
| **parent/guardian** | ✅ *uses the student account* | resolved by design — the student login's email is the parent's; delivery reaches them there | not a separate role | X1 |

**The three that matter most** (each **Critical**, each a **capability gap**):

1. **The enrollment wall** — a big school *cannot get turned on*. (Theme A.)
2. **No delivery at scale** — across 120 events, photos reach almost no one. (Theme C.)
3. **No organizing structure** — everything is a flat list; this one gap quietly causes several others. (Theme B.)

Everything else is friction on top of a product that, at 800 students, can't be enrolled or delivered.

---

## 3. The review — walked per role

### 3.1 Platform admin (the operator — us) · lands on `/schools`

**Job (`00` §3):** onboard a school + its first admin; oversee the estate. Infrequent, back-office.

**Holds up.** `/schools` has rollups + search/sort (BP2), create-school + add-admin (shown-once temp
password), and an admin roster. With a handful of schools, the absence of pagination is a non-issue.

**Breaks at scale — the operator is blind to adoption.** The estate list shows *structure* (how many
admins/teachers/students/events a school has) but not *health*. A school that CSV-imported 800 students and
**enrolled zero of them** — stuck at the enrollment wall (§3.2) — is visually identical to a school humming
along. There is:
- no **adoption funnel** per school (staff → students *enrolled* → events → distributed → *delivered*),
- no **stalled-school** alert ("imported 800, enrolled 0, 0 events in 30 days"),
- no **usage/storage/last-activity** trend, and no capacity signal beyond `max_teachers`.

→ **Fails T4 / P1 / X4.** Severity **Medium** (few operators, but they're flying blind on customer success).
**Gap type:** display+capability (the counts exist; the funnel/trend framing and a couple of new aggregates
don't).

**Ideal.** An estate command center: per-school funnel + stalled-school alerts + usage rollups — BP1's
dashboard pattern, lifted to the platform tier. (Roadmap: **BP14**.)

---

### 3.2 School admin (the buyer — accountable for the whole program) · lands on `/dashboard`

**Job:** stand up and run the school — staff, students+enrollment, events, oversight. Wants **control +
visibility**. This role feels the scale pain hardest, because they own the setup.

**Holds up.** The BP1 command center + BP7a setup checklist; staff/students/events lists with counts +
search + filter (BP2); the download audit (BP8b); notify + roster (BP4). At demo scale this is a genuinely
good admin surface.

**Breaks at scale:**

- **① The enrollment wall — the product can't be switched on. (Critical, capability.)** BP7d CSV import
  creates students **name+email → photoless → `pending`** (≤500/batch). The *only* way to attach a face is
  BP7d-2's one-at-a-time **"Add photo"** on each student's detail page. For 800 students that's **800
  sequential manual uploads** — days of clicking before a single photo can be matched. Enrollment is the
  gate to *all* value (no face → no match → no distribution), and it is the single least-scalable action in
  the app. → **Fails X4 / T8 / P5.** *This is the highest-severity finding in the review.*

- **② No organizing structure — a flat 800-row world. (High, capability.)** Students have **no class /
  grade / section**; events have **no term / category / tag / calendar**. Schools think and operate in
  "Grade 3B" and "Fall term"; the app gives one flat 800-row students table and one flat 120-row events
  list (queries are `WHERE school_id` only — §5). This *one* absence causes three downstream failures:
  **delegation** (can't hand a class to its homeroom teacher), **findability** (§3.3, §3.4), and **reporting**
  (§3.2④). → **Fails P3 / P5 / X5.**

- **③ Bulk actions don't exist. (High, capability.)** The dashboard alert "43 enrollments failed" is not
  *actionable* — there's no bulk re-enroll; you click into 43 students one by one. Same for archiving
  events, and (for teachers) triaging matches (§3.3③). Everything is one-at-a-time; at scale that's the
  defining friction. → **Fails P5.**

- **④ Oversight is point-in-time, not a program view. (Medium, display+capability.)** The dashboard is
  *live counts* — enrolled/pending/failed, events, photos. An admin accountable for the program can't
  answer "how did distribution go **this term**?", "how many of my 800 students have **ever signed in**?",
  "which events **reached** their audience?" There are no trends, no delivery/engagement rates, no per-term
  rollups. → **Fails T4 / P8 / X4.**

- **⑤ Findability & lag. (Medium, mixed.)** 120 events in one flat chronological list — no term/category
  filter, no calendar, no date range; find-by-scroll or hope you named it searchably. And every list
  **fetches all rows then filters/sorts client-side** (§5), so at 800 students the page is heavy and search
  is over an already-huge payload. → **Fails P5 / D8.**

**Ideal.** A command center with **trends + drill-down**; **class/term structure** with **delegation**;
**bulk everything**; **fast, server-searched, paginated** lists; **bulk photo enrollment** so the school
switches on in an afternoon, not a fortnight.

---

### 3.3 Teacher (staff — running events *alongside* teaching, wants speed) · lands on `/dashboard`

**Job:** create event → upload → distribute → browse/triage galleries. Doing it between classes; wants it
fast and low-friction.

**Holds up.** Events list/create, multi-file upload with per-file progress, Process + live status polling,
the gallery (All / By-student / **Needs review**), photo-detail correction (confirm/reject/report-a-miss,
BP5), and Notify (BP4).

**Breaks at scale:**

- **① "My events" doesn't exist. (Medium→High, mixed.)** The events list is the **whole school's 120
  events**, not the ones *this* teacher runs — no ownership, no "mine", no calendar. A teacher who ran three
  events this week must find them in a 120-row list shared with every colleague. → **Fails P1 / P5.**

- **② Verification is a one-at-a-time slog. (High, capability.)** The **Needs review** lane lists ambiguous
  matches; each is confirmed/rejected individually on the photo detail. There's **no batch confirm/reject**,
  **no sort by confidence**, **no "auto-confirm ≥ 0.9."** At demo scale (5 items) it's fine; at 100+
  ambiguous matches across a 2000-photo event it's unusable, so in practice review gets skipped — which
  quietly defeats the whole BP5 trust loop. → **Fails P5 / X2.**

- **③ Upload at volume is fragile. (Medium, mixed.)** 30 MB/file cap, **no inline retry** on a failed file,
  no folder/zip intake, not resumable. A real event day is hundreds-to-thousands of photos over flaky
  school wifi; one dropped upload is a silent hole. → **Fails P6 / X3.**

- **④ Gallery lag & no in-gallery navigation. (Medium, mixed.)** A 2000-photo event renders **every tile**
  (each tile lazily fetches its own signed URL, which is good; but 2000 DOM nodes + 2000 Intersection
  Observers is not; §5). There's no in-gallery **filter** ("only needs-review", "only student X") and no
  **jump-to**; the By-student tab renders a chip per student (200 chips for a big event). → **Fails P5 / P9.**

**Ideal.** "My events" + a calendar; **batch review** with confidence sort and an auto-confirm threshold;
**robust bulk upload** (retry, folders); **paginated, filterable, jump-able** galleries. *(Cohort-scoped
matching — narrowing an event to a grade to cut false matches — is **skipped for now**, owner call.)*

---

### 3.4 Student (the recipient — young, low tech-tolerance, cares about *their* memories) · lands on `/me/events`

**Job:** find and download the photos they're in; feel it's private.

**Holds up.** The `/me/events` "My Photos" page is genuinely nice at demo scale — Pinterest-grade
natural-aspect masonry (BP3), the authoritative **"new photos" banner + nav badge** (BP4), download-all
(client-zip), appearances hidden from students, and self-serve "this isn't me" (BP5).

**Breaks at scale:**

- **① The 60-event / 900-photo firehose. (High, mixed.)** A 3rd-year student appears in ~60 events. The
  event filter is a **horizontal chip bar** — 60 chips, overflowing, with **no grouping by year/term, no
  search, no favorites/albums**. Pick "All" and it's **900 photos** in one masonry with **no pagination or
  virtualization** — janky scroll. **Download-all buffers every blob in memory** (`use-download-all.ts`
  even comments "modest set (tens of photos)"; §5), so a real student's "save everything" likely stalls or
  OOMs. → **Fails P5 / P9 / D8.**

- **② The photos never *arrive*. (Critical, capability.)** Distribution is **in-app only** (BP4) — no
  email, no push. The student sees photos **only if they log in and go look.** A 7-year-old has no login
  habit and, often, no device. Across 120 school events a year, the honest outcome is that **most photos
  are never seen by their subject.** For a product whose *name is distribution*, this is the defining
  failure, and scale multiplies it 120×. → **Fails X1 / T1.** (The fix is **outbound email to the student
  account** — §3.5 + **BP12**.)

**Ideal.** Photos **organized by year/term**, **searchable**, with **albums/favorites**; a **performant,
paginated** browse; a **download-all that survives 900 photos**; and — above all — a **signal that reaches
them** (outbound email to the student account — the parent's, for a young child) when photos land.

---

### 3.5 Parent / Guardian — resolved by design: they use the student account

**No separate role needed.** `00` §3 lists parent/guardian as *not modelled*, and for a young child the
parent is the real recipient. **Owner decision (2026-07-25): the parent simply uses the student's account.**
This works because a student login already carries an **email** (set at create / CSV import) — for a young
child that address is typically the parent's. So the delivery signal (§3.4②) reaches the parent **through
the student account**; there is no guardian persona, contact model, or separate login to build.

What remains is the delivery itself: it's still **in-app only** (no outbound email yet). So the open work is
**outbound email to the student account's address** (+ an optional **share link**) — not a guardian data
model. That *simplifies* the distribution phase rather than adding to it.

→ **Resolved** by design; folds into **BP12**, now scoped to *email to the student account + share link*
(no guardian modelling). Consent/legal stays out-of-band per `00` §1.

---

## 4. Cross-cutting themes — the engine behind the per-role gaps

The role findings above rhyme. Nine themes generate almost all of them; the roadmap (`04-improvement-roadmap-round-2.md`) is organized
around *these*, because fixing a theme fixes it for every role at once.

| # | Theme | Roles hit | Lens | Gap type | Severity |
|---|---|---|---|---|---|
| **A** | **Enrollment wall** — no bulk *photo* enrollment; CSV makes photoless students, faces are 1-by-1 | school admin | X4/T8/P5 | capability | **Critical** |
| **B** | **No org structure** — classes/sections + event term/category; unlocks delegation, findability, reporting | admin, teacher, student | P3/P5/X5 | capability | **High** |
| **C** | **Distribution reach** — in-app only; no outbound email/push, no share link (delivery targets the student account) | student, staff | X1/T1 | capability | **Critical** |
| **D** | **Performance-as-UX** — unbounded lists + in-Python roster loads + all-tiles galleries + OOM download-all; **no thumbnails (full-res everywhere)**; client-only search | every role | P5/D8 | mixed | **High** |
| **E** | **No bulk actions** — re-enroll, archive, batch confirm/reject, multi-select photos | admin, teacher | P5 | capability | **High** |
| **F** | **Findability** — no global search, recents, favorites, date filters, calendar; no in-gallery filter/jump; chip overflow | every role | P5/P3 | mixed | **Medium** |
| **G** | **Program analytics / trends** — point-in-time counts only; no delivery/engagement over time | platform + school admin | T4/P8/X4 | display+capability | **Medium** |
| **H** | **Accuracy at scale** — no re-enrollment cadence/staleness; no per-event expected-vs-matched ("who's missing?") reconciliation *(cohort-scoped matching skipped for now, owner call)* | teacher, admin | X2/P7 | capability | **Medium** |
| **I** | **Lifecycle at scale** — no bulk archive; no event hard-delete (deferred BP8e); no retention/expiry | admin, ops | X3 | capability | **Medium** |

**A — Enrollment wall.** The one that stops the product cold. CSV import (BP7d) + in-place set/replace
(BP7d-2) were built *bulk-first for the roster*, but the **photo** — the thing enrollment actually needs —
stayed one-at-a-time. A big school can create 800 student rows in two CSV pastes and then hit a wall.

**B — No org structure.** The highest-leverage *structural* gap. A single `class`/`group` concept (with
membership) + `event.term/category` would let the school delegate to teachers, filter/scan by cohort, and
report per class/term. Its absence is why several separate role findings exist. *(Using the cohort to also
scope face-matching is a natural extension — **skipped for now** per the owner.)*

**C — Distribution reach.** The flagship gap, known since Round 1, made worse by scale. BP4 built the
in-app signal *and the multi-channel notifier seam* — but the **outbound channel** (email) was left as a
future drop-in. Delivery targets the **student account's email** (the parent's, for a young child — §3.5),
so no guardian model is needed. At 120 events, "queryable if you log in" means "unseen."

**D — Performance-as-UX.** Not filed under "tech" here because at Greenfield scale it *is* the felt
experience: slow lists, janky galleries loading **2000 full-res images** (no thumbnails exist), a
download-all that stalls. Fixed by pagination + server search + de-rostering the gallery paths (**BP9**) and
**image thumbnails/derivatives** (**BP17**) — the latter also puts a small avatar on each student-list row
(the compact thumbnail when present, the full-res URL as fallback).

**E–I** are the second tier: batch operations, findability, program analytics, accuracy-at-scale, and
lifecycle. Each is real at 800 students / 120 events but none blocks core value the way A/B/C do.

---

## 5. Grounding — the evidence behind the scale claims

So this review is falsifiable, not hand-waved. (Paths relative to repo root; line numbers as of the snapshot.)

**Lists are unbounded; only the audit log paginates.**
- Paginated: `services/backend/src/backend/api/routers/audit.py:43` (`limit`/`offset`/filters) →
  `adapters/repositories/postgres_download_audit.py:103` (`.offset().limit()`).
- Unbounded (full-set `SELECT … WHERE school_id`, no `LIMIT`): students
  `postgres_students.py:105`, events `postgres_events.py:95`, staff `postgres_users.py:122`, schools
  `postgres_schools.py:46`, event media `postgres_media.py` (`list_by_event`).

**Galleries load the whole school into Python and filter in memory.**
- `services/backend/src/backend/services/gallery_service.py` calls `list_by_school(...)` (the **full**
  roster / event list) then filters to the few that appear — `:162` (`event_students`), `:190`
  (`student_events`), `:220` (`media_appearances`). Opening one event's *By student* tab in a 500-student
  school loads all 500 + all match rows for that event; `adapters/repositories/ml_results.py`
  (`list_event_appearances`/`list_student_appearances`, called at `:158`/`:186`) loads **all** matches per
  event/student with no LIMIT.

**Front-end search/sort/filter is client-side over already-fetched rows; grids mount every tile.**
- `frontend/app/(school)/students/page.tsx:189` and `events/page.tsx:141` (`.filter()`/`useSort` in memory).
- `frontend/components/gallery/photo-grid.tsx:51` renders every item; per-tile URL fetch is lazy
  (`photo-tile.tsx`, `useInView`) but the DOM/observer count is not bounded.
- `frontend/lib/hooks/use-download-all.ts:57` buffers all blobs and comments "modest set (tens of photos)".

**No organizing structure; no thumbnails; guardian = student account.**
- Schema (`00` §4): `School → {User, Student, Event → Media → Appearance}` — no class/section on Student, no
  term/category on Event.
- **No image thumbnails/derivatives** exist — full-res only (`00` §2, §9); `StudentAvatar` even ships a
  wired-but-unused `photoUrl` reserved for a future thumbnail (`00` §7a; decisions/0033).
- Parent/guardian: intentionally **not** a separate role — the parent uses the student account (whose email
  is theirs), so delivery reaches them there (owner decision, §3.5).

---

## 6. What this implies — over to the roadmap

The review says the same thing three ways: **at 800 students / 120 events, the product can't be turned on
(A), can't deliver (C), and organizes nothing (B)** — and, underneath, its lists and galleries weren't
built to hold that much (D). Those are the core gaps by **severity**. The **build order** (owner-delegated)
— which lives in its own file, **`04-improvement-roadmap-round-2.md`** — leads instead with the cheapest
high-value work and **defers three phases to the back**: **BP9** scale-ready lists/galleries +
**BP17** image thumbnails/derivatives (the fast-UI pair — BP9 fixes the queries, BP17 the images) →
**BP10** bulk enrollment (A, the switch-on) → **BP11** org structure (B) → **BP13** bulk actions (E) →
**BP14** program analytics (G) — then the deprioritised **BP12** distribution reach (C, now *email to the
student account + share link*), **BP15** accuracy at scale (H), and **BP16** lifecycle (I). Distribution
stays a **Critical** finding — deferred on **effort/infra**, not importance.

Each BP9+ phase is a separate, reviewable slice with its own `decisions/` record, gate, and 2× review loop
— built only on explicit approval, per repo convention.
