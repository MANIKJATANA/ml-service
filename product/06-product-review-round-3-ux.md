# 06 — Product Review, Round 3: UX-first, post-BP9–17

> **This file = "how the product actually feels now, walked as each user."** Round 2 (`02-product-review.md`)
> judged the product at scale and produced the BP9–BP17 track; all of it has landed ([decisions/0055–0062](../decisions/)).
> This review does the two things that round could not:
>
> 1. **Re-test Round 2's claims** against the shipped code — did BP9–17 actually close what `02` opened? (§3)
> 2. **Walk fresh, UX-first** — every role as that user (platform admin, school admin, teacher, student, and the
>    parent reading over the student's shoulder), first-run *and* at Greenfield scale, plus six senior-PM
>    cross-cutting sweeps (core-job trace, IA/design bar, feedback matrix, a11y/mobile floor, trust/privacy,
>    instrumentation honesty). (§4–§5)
>
> _Snapshot: 2026-07-28 · commit `bce5b59` · BP1–BP17 complete, build track paused ([decisions/0063](../decisions/0063-park-remaining-backlog.md))._
> _Method + scope decisions recorded in [decisions/0064](../decisions/0064-product-review-round-3-ux.md)._

---

## 1. How to read this review

- **Method.** Static, code-grounded: 12 review agents (4 persona walks · a leads-verifier · an R2 re-tester ·
  6 PM sweeps) each reconstructed what the user sees from the page components, hooks, and backend routers —
  loading/empty/error/success states, copy, affordances — then every finding was deduped on root cause and
  calibrated in one sitting. **Every claim carries file:line evidence read this round**; absence claims carry
  the grep trail. Findings cite lens IDs from `01` §3 (**D1–D8** design craft · **P1–P10** product-UX ·
  **X1–X6** domain). A separate verification loop re-opened the citations before this doc was finalized.
- **Severity** (extended from `02` §1 — Critical gains the written no-workaround test; High gains the D8-floor
  and trust-miscommunication clauses): **Critical** = blocks the core value / a user class permanently locked
  out or trust broken, **no workaround** (each Critical carries its written no-workaround test) · **High** = a
  role's primary job painful or degraded at scale, or the D8 floor broken on a primary surface, or a trust
  miscommunication on a primary surface · **Medium** = friction, workaround exists · **Low** = polish (bundled).
- **Gap type** (from `03` §1): **display** = the data already flows, the product doesn't show it (cheap) ·
  **capability** = doesn't exist end-to-end (expensive). Decided against the backend routers, cited.
- **Static-review disclaimer.** No running stack (the FE live smoke is still pending, `05` §D). Claims about
  *rendered feel* — mobile layout at 375px, contrast in situ, animation, SR timing — are labeled
  **`unverified-runtime`** with the static signal that motivated them, and the worst offenders are listed in
  §7c as candidates for the pending live check. They are capped at High.
- **Leads discipline.** A pre-review sweep produced 25 candidate rough edges; a verifier agent confirmed 10,
  partially confirmed 4, and **refuted 11** (including four invented UI elements and one falsely-alleged
  absence). Only confirmed/partial leads appear below; the refuted ones are recorded in §7b so no future round
  re-chases them.
- **Parked items are excluded by owner decision** (2026-07-28): BP12 outbound email/share-links, BP15
  staleness/reconciliation, BP16 hard-delete/retention, and the BP6 video timeline are *not* re-reported or
  re-ranked. Where a finding's evidence trail touches one, it says `(parked: BPnn)` in one line and moves on.
- **Finding IDs** (`R3-<agent>-<nn>`) are stable — the roadmap (`07`) references them. **A1–A4** = the four
  persona walks (§4.1–4.4); **S1–S6** = the six PM sweeps (§5.1–5.6). Gaps in the numbering are candidate
  findings dissolved during dedup; within each section, findings are ordered by weight, not ID.

---

## 2. Scorecard — the estate at a glance

| Role | The job post-BP9–17 | What still breaks | Worst finding | Lens |
|---|---|---|---|---|
| **platform_admin** | ✅ estate funnel + stalled alerts + rich school detail | ⚠️ the school record is **write-once** (no rename / cap-raise / suspend UI or API); activity recency collected but invisible | R3-A1-01 | X4/X5 |
| **school_admin** | ✅ genuinely strong: checklist, bulk import/enroll, classes, batch review, analytics | ⛔ **holds the destructive lever unknowingly**: a lost student credential can only be "fixed" by a delete that erases the child's photo history; one-way doors (can't-clear tags); works blind on reach | R3-A2-01 | P6/P7/X4 |
| **teacher** | ✅ fast event→upload→process→triage loop, focus scoping, batch review | ⚠️ review = **guesswork beyond their own classes** (no reference face shown); events list never shows distribution state; review debt invisible at the announce moment | R3-A3-02 | X2/P1 |
| **student** | ✅ Pinterest-grade masonry mechanics, streaming save, "not me" | ⛔ **can be permanently locked out** (no recovery path); the arrival moment is inverted — new photos buried under three years of history; 60-chip event wall | R3-A4-01 | P6/X1/P5 |
| **parent (via student account)** | ✅ jargon-free copy on the student surface | ⚠️ told **"Only you can see these"** — structurally false; face recognition never explained anywhere | R3-S5-02/03 | P7/D6 |

**The three that matter most:**

1. **Recovery has no path** *(Critical, capability)* — a student who forgets their password is permanently cut
   off, and the only remedy destroys their photo history. Three agents nominated this independently. (Theme J.)
2. **The pipeline can strand, silently** *(Critical, capability)* — a lost or dead-lettered processing job
   leaves an event saying "Distribution is running" forever, with no in-product unstick, no staleness cue, and
   zero failure metrics. (Theme K.)
3. **The product neither lands nor measures its last mile** *(High, mostly display)* — the student's "new
   photos" moment points at nothing and the badge freezes in an open tab; staff's "Delivery rate" measures the
   announce button, not the audience; per-event opens/saves exist in the DB and reach no screen. (Themes L+O.)

Everything else is friction on a product that — unlike at Round 2 — **can** now be switched on, organized, and
operated at 800 students. Round 3's problems are the last mile, the failure paths, and the words.

---

## 3. Round 2 → Round 3: what shipped, and did it land

The R2 re-test walked every claim in `02` (scorecard cells, the numbered per-role findings, all nine themes,
and each §5 grounding bullet — 43 rows) against the current code. **Counts: 32 RESOLVED · 5 PARTIAL ·
2 UNRESOLVED · 4 PARKED · 0 REGRESSED.** (The table below shows the headline rows; the counts refer to the
full 43-row ledger.)

| R2 claim (§) | Fix | Verdict | Evidence now |
|---|---|---|---|
| A — enrollment wall (Critical) | BP10 + BP7d | **RESOLVED** | `students.py:100` `/match-photos`; pooled `use-bulk-photo-enroll.ts`; "Retry failed (N)" `students/page.tsx:279` |
| B — no org structure (High) | BP11a/b/c | **RESOLVED** | full classes CRUD `classes.py:40-160`; category/term/date filters `events.py:81-84`; tz-safe calendar `lib/events/calendar.ts:11` |
| C — distribution reach (Critical) | BP12 | **PARKED** | owner call, `05` §A — excluded here |
| D — performance-as-UX (High) | BP9 + BP17 | **RESOLVED** | `.offset().limit()` in all five repos (e.g. `postgres_students.py:227-228`); de-rostered galleries `gallery_service.py:163`; 48-tile windowing `photo-grid.tsx:21`; streaming zip `use-download-all.ts:44`; thumbnails `galleries.py:112` |
| E — no bulk actions (High) | BP13 (+BP10) | **RESOLVED** | `events.py:122` `/bulk-status`; batch review `review.py:97`; multi-select grid `photo-grid.tsx:58` |
| F — findability (Medium) | BP9/BP11b partial | **PARTIAL** | per-list search/filters/calendar shipped; **no global search/recents/favorites** (grep hits only `design/pinterest.DESIGN.md`); the student 60-chip bar (→ R3-A4-03) and the staff by-student chip bar (accepted residue → R3-A3-11 Lows) untouched |
| G — program analytics (Medium) | BP14 | **RESOLVED** | `/analytics/school` + `/estate` (`analytics.py:36,46`); `touch_last_login` `postgres_users.py:124` |
| H — accuracy at scale | BP15 | **PARKED** | `05` §A |
| I — lifecycle | BP16 (archive via BP13) | **PARKED** | `05` §A |
| §3.3③ upload robustness | none | **UNRESOLVED** | zero retry paths in `use-media-upload.ts`; no folder/zip intake → R3-A2-09/S3-05 |
| §3.4① student chip firehose | none | **UNRESOLVED** | still one chip per event `me/events/page.tsx:195` → R3-A4-03 |
| BP3/4/5 student praise set | — | **intact** | masonry/banner/"not me"/badge all still mounted (`me/events/page.tsx:99-104,177-183`; `app-shell.tsx:156-157`) |

**Design-bar verdict (re-judging `01` §4 after BP9–17):** **Linear — delivered, now stronger** (server-driven
lists, counts, bulk bars everywhere). **Stripe — substantially closed on capability** (rates, trends, per-term,
funnel, tabular numerals on every numeric cell), with presentational polish left (bare funnel counts, one raw
enum pill). **Pinterest — half-closed:** the *grid mechanics* now genuinely hit the bar (natural aspect, 16px
radius, hover-zoom + hover-download, thumbnails, streaming save), but the *chrome* thesis was never attempted —
the student sits in the identical white admin shell with a one-item sidebar, cool-gray tokens, and an
admin-white lightbox panel (R3-S2-05). The scale complaints of `02` §5 are, structurally, gone.

---

## 4. The review — walked per role

### 4.1 Platform admin (the operator — us) · lands on `/schools`

**Holds up.** Day-0 is clean: empty state invites, create-school validates, add-admin hands off a shown-once
credential well, and the roster's "Awaiting sign-in" → "Active" pill is a real adoption signal. The estate page
**does** catch R2's stalled scenario: 800-imported/0-enrolled renders an error card — "800 students imported,
none enrolled — not switched on yet" + "View school →" (`estate/page.tsx:79-87`). The schools list at 20 rows
is Stripe-adequate; the teacher-cap cell (`"{teachers} / {max}"` flipping to warning at cap,
`(platform)/schools/page.tsx:213-216, 248-252`) is the most Stripe-grade cell in the app.

- **R3-A1-01 · High · X4/P6/X5 · capability — the school record is write-once.** The only school mutation in
  the API is the admins PATCH (`routers/schools.py:116`); grep for update/rename/set_max/suspend across backend
  and FE → nothing. Yet `suspended` is a rendered status pill *and* actively enforced
  (`onboarding_service.py:101` `raise ValidationError("school is suspended")`), and `max_teachers` is set once
  at create with a hint that explains the range, not the meaning (`schools/page.tsx:102`). When Greenfield
  outgrows its cap the list warns "Teacher limit reached" (`:213`) and the operator's only lever is DB surgery.
  Quota management and offboarding — the operator's core day-2 jobs — have no product path. *(High, not
  Critical: core value keeps flowing; the operator persona has out-of-product access.)*
  → Add `PATCH /v1/schools/{id}` (name, max_teachers, status) + Edit/suspend UI.
- **R3-A1-02 · Medium · P6/P7 — "Resend invite" is an unconfirmed, mislabeled password reset.** It
  unconditionally replaces an **active** admin's working password (`onboarding_service.py:165-169` regenerates +
  `must_change_password=True`) yet fires from a single click beside "Disable" (`schools/[schoolId]/page.tsx:165-170`),
  with no ConfirmDialog anywhere on the platform surfaces (grep → 0). The operator handling a real lockout may
  never realize this button *is* the remedy; the misclick is one pixel away. Same pattern on the staff page
  (R3-S3-03). → Confirm + state-aware copy ("This replaces their current password").
- **R3-A1-03 · Medium · X4/P1 — a never-started school reads "Healthy".** `stalled = students > 0 and
  enrolled == 0`; `idle` requires `enrolled > 0` (`analytics_service.py:184-186`) — so a school that was
  onboarded and then *nothing happened* (zero students, admin never signed in) falls through both flags into
  the success pill (`estate/page.tsx:56`) and is excluded from the alert cards (`:60`). R2 §3.1's "a stuck
  school looks like a thriving one" survives BP14 for exactly the worst cohort. → A third `not_started` flag.
- **R3-A1-04 · Medium · X5/P2 — last-activity is collected but invisible.** `users.last_login_at` is stamped on
  every login (`auth_service.py:56`) and appears in **no** API response or screen (grep `last_login` in
  frontend → 0; `UserResponse` has no such field). The operator answering "did the admin we re-invited ever
  come back?" gets a binary pill and a 30-day idle heuristic with no dates. → Expose it (roster "Last sign-in"
  column, school "Last active"). *(The pricing-lever consequence is R3-S6-04.)*
- **R3-A1-05 · Medium · P8 — the adoption funnel can't be ranked.** Eight plain columns (six numeric) in
  school-creation order (`estate/page.tsx:122-129`); `SortableHead` exists two pages away and isn't imported.
  Since the alert cards don't catch every laggard (A1-03), the table is the fallback triage tool — unsortable.
  *(Lead L12 confirmed.)* → Client-side sort over the already-loaded array.
- **R3-A1-06 · Low (bundled).** Login screen carries zero product identity (also R3-S2-03); create-school
  success doesn't route to the new school where the next step lives; no per-page `<title>` anywhere (one root
  `metadata`, `app/layout.tsx:19-22` — also R3-S2-08); "Estate health" is operator jargon; duplicate school
  names accepted and indistinguishable; EstateSkeleton covers only the stat cards; platform-admin self-lockout
  has no reset even in the CLI (`bootstrap_admin.py:34` no-ops on an existing email — workaround: bootstrap a
  second admin); estate "Every school is on track" renders even with zero schools.

### 4.2 School admin (the buyer) · lands on `/dashboard`

**Holds up — this is a genuinely good admin product now.** The forced password change works; the day-0
checklist still guides enroll→event→upload→distribute with the teacher step correctly optional
(`dashboard/page.tsx:225-248`); staff/classes have proper skeletons (leads L1/L2 refuted); CSV import → bulk
photo enroll → retry-failed closes R2's enrollment wall; batch review is confidence-sorted with a guarded
reject-all; processing changes are SR-announced (`events/[eventId]/page.tsx:581`); analytics rates are legible
and zero-denominator-safe.

- **R3-A2-01 · CRITICAL · P6/P7/X4/X5 · capability — student credential loss has no recovery path, and the
  only remedy destroys the child's photo history.** Nominated independently by three agents (A2, A4, S5).
  The chain, all code-verified: **(a)** no self-serve reset exists for anyone (grep `forgot` across FE + BE →
  0; `reset` hits only unrelated UI/state code — zero password-reset paths; `auth.py`'s only password mutation
  requires the current password, `:42`); **(b)** resend-invite
  exists **only** for teachers/admins (`staff.py:96`, `schools.py:131`) — `students.py`'s full route inventory
  (58–237) has no credential endpoint; **(c)** the documented workaround, delete-and-recreate (BP7d), is no
  longer a workaround: BP8e's erasure purges the student's matches (`ml_service/orchestration/enrollment.py:152`
  `delete_by_student`) *and* re-processing can never rebuild them for the new student id because the worker
  skips completed media (`inference.py:59` + `:122-124`) — the only rebuild is staff hand-adding the child to
  ~900 photos via report-a-miss. The UI steers staff into the trap: the student detail's only credential-adjacent
  action is Delete ("This can't be undone.", `students/[studentId]/page.tsx:442`). At 800 students with
  temp passwords handed out on paper slips, forgotten credentials by March are a statistical certainty — and
  each one either permanently locks a child out of the core value or destroys that value to restore access.
  **No-workaround test: all four doors checked (self-reset / staff resend / admin set-password / non-destructive
  recreate) — none opens.**
  → **Fix is small:** `POST /v1/students/{id}/resend-invite` mirroring BP7c's machinery (regenerate +
  `must_change_password` + the existing `InviteResultDialog`), plus one login-page line ("Forgot your password?
  Ask your school."). Effort S.
- **R3-A2-02 · High · P6/X4 — the one-time credentials CSV can be silently discarded.** Closing the bulk-import
  results dialog (Esc/overlay/Done) unconditionally resets it (`bulk-import-dialog.tsx:65-68`); the copy warns
  ("Download the temporary passwords now — they won't be shown again.", `:204`) but nothing tracks whether
  Download was clicked or guards the close (`:231-234`). One keystroke after importing 500 students, every
  credential is gone — and per A2-01 each affected student funnels into the destructive path. Same trap on the
  single-invite dialog (`invite-result-dialog.tsx:47-50`, R3-S3-02). → Close-guard when not yet downloaded.
- **R3-A2-05 · Medium · P6/P10 — event tags are one-way doors.** Once set, category/class/term can never be
  cleared: the edit dialog deliberately omits the empty option ("Once categorized, clearing isn't supported
  (0027)", `events/[eventId]/page.tsx:160-161`; "Once tagged…" for the class field, `:187-188`; "Emptying an
  optional field leaves it unchanged", `:123`). Aggravator: create-event **silently preselects "Other"** (`events/page.tsx:94-99`), so
  default-accepted events are permanently categorized (lead L18 partial). A mis-tagged class actively
  mis-scopes teacher focus lists forever; the only true undo is recreate-and-reupload. → Explicit-null clearing
  in the PATCH + restore the "No category"/"School-wide" options.
- **R3-A2-04 · Medium · P2/X4 — the teacher cap is invisible on the school side.** The "N of M allowed" figure
  exists only on the platform surface (`schools/[schoolId]/page.tsx:333`); the school's own staff page shows a
  bare count (`staff/page.tsx:321-323`) and the cap surfaces as a post-submit 409 toast (`:73`). *(Lead L9.)*
  → Expose `max_teachers` on a school-admin read; annotate Add-teacher at cap.
- **R3-A2-06 · Medium · P5/X4 — class assignment doesn't scale to the CSV world.** Building 25 classes over 800
  students is ~800 individual search-and-clicks (`classes/[classId]/page.tsx:101,133-138`); the CSV import
  carries no class column (`bulk-import-dialog.tsx:135`) and there's no paste-a-list path. BP11's organizing
  layer is priced out at exactly the scale it was built for. → A `class` CSV column or paste-emails bulk assign.
- **R3-A2-07 · Medium · P2/D6 — "Pending" hides "no photo — action is yours".** After a bulk import the list is
  a wall of amber "Pending" pills (`lib/students/enrollment.ts:14`, tone `warning`) that read like the system is
  working on it; the row already knows `reference_photo_path === null` and never says "No photo". The
  explanation lives only inside the import dialog most admins see once (`bulk-import-dialog.tsx:135`).
  *(Lead L8.)* → A "No photo yet" sub-label on photoless pending rows.
- **R3-A2-08 · Medium · P5/P3 — no list state survives navigation.** Grep `useSearchParams` across the whole
  `(school)` group → **0 matches**; every filter/sort/tab/scroll is component-local `useState`
  (`students/page.tsx:299-304`, `events/page.tsx:286`). The triage loop (filter to Failed → open → back)
  resets each round trip, and no filtered view is shareable. *(Lead L7 confirmed; also breaks the review
  deep-link, R3-S2-02.)* → Mirror q/sort/dir/status/tab into the URL.
- **R3-A2-03 · Medium · P5/P7 · display — the access log can't answer its own question.** `use-audit.ts:23-27`
  already plumbs `eventId`/`studentId`; the page never passes them and renders no filter UI
  (`audit/page.tsx:39-42`) — at thousands of rows, "who downloaded student X's photos?" is a 50-rows-at-a-time
  page-through. *(BP8b deliberately dropped the filter UI; at Greenfield volume that call has aged out.)*
  Deeper pivot gap: staff downloads are never linked to the child (`subject_student_id` is None for staff,
  `gallery_service.py:311-312` — R3-S5-10). → Wire the two selects; add a per-student drill-in.
- **R3-A2-09 · Medium · P6 — no per-file retry on the event uploader.** A failed file shows its error and keeps
  no handle (`upload/page.tsx:123-126`; grep retry in `use-media-upload.ts` → 0) — 20 failures out of 500 mean
  re-locating 20 files in the OS picker. *(R2 §3.3③ residual, still UNRESOLVED; the interruption half is
  R3-S3-05.)* → Keep `File` handles, add "Retry failed (N)".
- **R3-A2-10 · Medium · P5/P8 — the notify roster doesn't scale.** One unpaginated table of every matched
  student on the event detail (`events/[eventId]/page.tsx:316`; the endpoint has no limit/filter,
  `events.py:200-202`); the actionable cohort — "who hasn't opened?" — must be found by eye among hundreds of
  rows. → Collapse behind the summary + a Not-opened filter.
- **R3-A2-11 · Medium · P6/P2 — the CSV error loop is manual.** Preview pre-flags nothing
  (`bulk-import-dialog.tsx:179-184`); results can't export the failed subset — only credentials for created
  rows (`:110`) — so fixing 30 typo'd emails means hand-transcribing them into a new file. *(Lead L15.)*
  → Pre-flag in-file duplicates/invalid emails; "Download skipped rows".
- **R3-A2-12 · Low (bundled).** Resend-invite unconfirmed (→ R3-S3-03); review-tab badge counts photos while
  the dashboard counts pairs — same word, different N (`gallery/page.tsx:403`); "Reject all remaining" acts on
  all pairs including selected (`:393`); audit "Photo" column labeled with the event name (`audit/page.tsx:121`);
  the forced change-password page never says *why* (`change-password/page.tsx:50`); calendar pills carry no
  photo/status scent; retry-failed silently caps at 1000; no search-match highlighting anywhere (lead L19).

### 4.3 Teacher (staff running events alongside teaching) · lands on `/dashboard`

**Holds up.** The shell is honest — nav is Dashboard/Students/Events and every target works with teacher
permissions; the DistributionCard (incl. the Opened roster) **is** teacher-visible; focus defaults to "My
classes"; batch review + guarded reject-all are exactly the between-classes tools R2 asked for.

- **R3-A3-02 · High · X2/P3 · display — the review lane offers no reference face.** A review tile is photo +
  name + % (`gallery/page.tsx:366-371`; `MediaReviewCandidate` = id/name/confidence, `types.ts:260-264`).
  A teacher personally recognizes ~their 2 classes of 800 students; "Is this Priya Sharma? 71%" against a group
  photo, with no picture of Priya and no face-box, degrades review to guessing for most names — and wrong
  confirms leak wrong photos to wrong students, the exact thing BP5 exists to prevent. The fix is already
  built: the reference-photo endpoint is teacher-permitted (`students.py:186-187`) and `StudentAvatar` +
  `useStudentReferencePhoto` are in use one page away (`students/page.tsx:188-194`). → Render the candidate's
  thumbnail in the review tile + `AppearanceRow`. *(Face-box overlay = the M–L extension; bbox data exists
  ML-side with no API.)*
- **R3-A3-01 · High · P1/X1 · display — the events list never shows distribution state.** Columns end at
  Processing (`events/page.tsx:525-530`) while `notified_at`/`auto_notify` are already on every row
  (`types.ts:168-169`); the dashboard alert says "N events ready to distribute" and links to a list where that
  state is invisible (`dashboard/page.tsx:60-63`). The teacher's core at-scale question — "which of my 6 events
  still needs me?" — takes 6 detail-page visits. → An "Announced / Not announced" pill (the exact BP4
  predicate), + deep-link the alert.
- **R3-A3-08 · Medium · X2/X1 — review debt is invisible at the announce moment.** The event detail — home of
  Process and Notify — never mentions review (grep `review` in `events/[eventId]/page.tsx` → 0); notify gates
  only on completed+active (`notification_service.py:106-109`); and `auto_notify` defaults **true**
  (`db/models.py:304`), so uncertain matches go student-visible the instant processing finishes (BP5's
  plain→allow). A hurried teacher processes → "All photos processed" → Notify, and discovers the review lane
  later or never (it's the third tab of a separate page — R3-S2-02's 5-hop scent). → "N matches to review"
  inside the DistributionCard + deep-link `?tab=review`; consider an announce-time confirm when debt > 0.
- **R3-A3-03 · Medium · P2/P1 — school-wide numbers sit on class-scoped lists.** Chip counts come from the
  school-wide dashboard rollup (`students/page.tsx:330-335`) while the list under them defaults to "My classes"
  (`:303`); "Failed (12)" can filter to zero visible rows. The dashboard has no `mine` parameter
  (`dashboard.py:31-33`). Numbers that don't match the list teach the teacher to distrust the numbers.
  → Drop/relabel the counts under focus, or thread `mine` through the rollup.
- **R3-A3-04 · Medium · P3/P1 — delegation is invisible to its beneficiary.** The FE fetches the teacher's
  classes and reads only `.length` (`students/page.tsx:311-313`); "My classes" never says *which*; a
  zero-class teacher gets no toggle, no hint delegation exists, and a full 800-row list with no explanation —
  indistinguishable from "the product has no scoping". → Name the classes on the toggle; a one-line hint for
  the unassigned.
- **R3-A3-05 · Medium · P5 — navigation tax on the speed path.** Create-event returns to the list without
  routing to the new event (`events/page.tsx:372-375`); the upload page's only exit is "Back to event" with
  Process one more page away (`upload/page.tsx:90,145`). The between-classes path "folder of 300 → processing
  started" is 8 interactions across 3 pages, and forgetting the final Process leaves photos pending with only
  a school-wide hint to catch it. → Route to the created event; offer "Process N photos now" on upload
  completion.
- **R3-A3-06 · Medium · P6/P2 — leaving mid-upload is silent loss.** No `beforeunload` anywhere (grep → 0);
  SPA-nav keeps the pool running but drops every status write (`use-media-upload.ts:51`), so failures land
  invisibly and the teacher can never learn which files to re-add. *(Merged app-wide as R3-S3-05.)*
- **R3-A3-07 · Medium · X1/D6 — "Notified 143 students" oversells a log line.** In the default deploy
  (`BE_NOTIFICATION_CHANNELS=log`) the toast (`events/[eventId]/page.tsx:235`) means: an in-app flag was set and
  143 log lines were written. The card copy hedges ("also sends via any configured channels", `:268-269`) but
  nothing shows *what is configured*, so the teacher reasonably believes families were messaged and stops
  there. *(Outbound itself: parked BP12 — this is the honesty of what's built.)* → State the mechanism
  ("Announced — they'll see it in My Photos") + surface the channel config.
- **R3-A3-09 · Medium · P5 — the triage round-trip resets itself.** The gallery Tabs are uncontrolled
  (`gallery/page.tsx:416`); "Open photo →" (`:373-377`) navigates away, and back re-lands on the All tab —
  re-click "Needs review" per doubtful photo. *(Lead L7's sharpest instance.)* → URL-addressable tab, or open
  the Lightbox (which already hosts the editor) instead of navigating.
- **R3-A3-10 · Medium · P5/P8** — the roster table again, teacher-flavored (see R3-A2-10).
- **R3-A3-11 · Low (bundled).** Boundary bounce is a wordless spinner→dashboard (`role-gate.tsx:25-28`) — an
  admin-sent `/classes/…` link just evaporates for a teacher; lightbox shortcut hints are `sr-only` and omit
  Esc (`lightbox.tsx:99-101`, lead L10); "Needs review" counts photos on the tab and pairs on the dashboard;
  per-page focus state is separate (`students` vs `events` each own `useState(true)`); the gallery's
  By-student tab still renders one chip per matched student (R2 §3.3④'s accepted residue — §3 row F).

### 4.4 Student (the recipient) · lands on `/me/events`

**Holds up.** The masonry mechanics are genuinely Pinterest-grade now (natural aspect, hover-zoom +
hover-download, windowed at 48, streaming download-all); the copy is jargon-free (zero ML terms leak — grep
verified); errors are kind and retryable; reduced-motion is real and global.

- **R3-A4-01 · CRITICAL** — the student side of R3-A2-01, from the login screen: no "forgot password", no
  "ask your teacher" hint — a locked-out family gets "invalid email or password" in a 5-second toast
  (`login/page.tsx:31`; `auth_service.py:23`) and a dead end. With a 14-day refresh ceiling
  (`settings.py:104`), any family that visits less than fortnightly re-enters the password every visit —
  lockout frequency is structural, not rare. *(Full chain + no-workaround test in §4.2.)*
- **R3-A4-02 · High · X1/P2 · display — the arrival moment is inverted.** The badge says "3 new" → the grid
  opens on photos from **three years ago**: the media stream is oldest-first (`postgres_media.py:165`
  `order_by(created_at)`), the new event is the *last* chip (`postgres_events.py:392`), the banner names no
  event and links nowhere (`me/events/page.tsx:183`), and every unseen flag is burned **on page load** —
  before anything was scrolled to (`:129` `markNotificationSeen` on mount). The backend already serves a
  newest-first announced list with per-event `unseen` (`notification_service.py:183`;
  `schemas/notifications.py:28`) — the FE reduces it to one number. Compounding: the badge itself is fetched
  **once per session** (`useMyNotifications` in the always-mounted shell with `revalidateOnFocus: false` and no
  interval — `components/ui/app-shell.tsx:156-157`, `swr-provider.tsx:13`), so a kept-open tab never lights up at all
  (R3-S3-11). BP4's flagship signal exists and then points at nothing. → Newest-first default; banner lists
  the unseen events as links; mark-seen on view, not mount; revalidate/poll the badge key.
- **R3-A4-03 · High · P5/P9 — the 60-chip event wall (R2 §3.4①, the surviving half).** All ~60 events render
  as flat wrapped chips in creation order, `event_date` discarded (`me/events/page.tsx:195`;
  `filter-chips.tsx:47` — no grouping/search/collapse). On a phone that's the entire first screen — pills, not
  photos — with the newest event last. → Chips ≤ ~8 events; beyond that, group by year/term (the date is in
  the payload) or a searchable select, newest first.
- **R3-A4-04 · High · X2/P6/P7 — "This isn't me" is a one-tap, unguarded, unrecoverable removal.** The only
  destructive action on the student surface sits directly under Download in the lightbox (`lightbox.tsx:171`),
  fires with no confirm (grep confirm in `(student)` → 0; the `ConfirmDialog` primitive exists unused),
  explains the consequence only after the fact ("Removed from your photos.", `me/events/page.tsx:56-57`), and
  has **no student-side undo** — recovery is a staff `match:review` action (`permissions.py:29`, granted
  `:48`/`:66`; the student set at `:69` holds only `gallery:view_own`) that no signal
  ever prompts, because staff are never told a student disputed (R3-S3-04). Operated by a child in a
  full-screen viewer, a mis-tap silently deletes a memory and quietly poisons the correction data. → Confirm
  with consequence copy + an undo toast (or a student-scoped un-reject mirroring `not-me`); surface student
  rejections to the staff review lane.
- **R3-A4-05 · Medium · P9/P2 — photos have no story.** Tiles carry `alt=""` and no caption
  (`photo-tile.tsx:158-161`); the lightbox's entire context is "812 of 900" + two buttons (`lightbox.tsx:144`)
  — never *which event, when*. The join is in memory on the same page (`media.event_id` × the events array).
  A memory product whose photos don't say what they're of. → Event name + date in the lightbox panel (and into
  `alt`).
- **R3-A4-07 · Medium · P9/P6 — the save is an unlabeled pile, and the fallback copy lies.** 900 memories land
  as `photo-001.jpg…photo-900.jpg` flat in `my-photos.zip` (`use-download-all.ts:39`); a single save is named
  by a UUID fragment (`use-download-to-disk.ts:30`). On non-Chromium browsers the buffered fallback silently
  truncates to the **first 500 — the 500 oldest** (`:152` + the ordering above), and the partial toast says
  "Try again to get the rest" — which deterministically re-downloads the same 500 (`me/events/page.tsx:44`),
  then auto-dismisses in 5s. → Name entries `{event}/{date}-{nnn}`; honest capped-path copy ("use an event
  filter / Chrome for all 900"); sticky partial toasts.
- **R3-A4-08 · Medium · P6/P7 — account life is a dead end.** Voluntary password change is unreachable (grep
  `href="/change-password"` → 0 — forced redirects only); the shell shows email + "Student", never the child's
  *name* (`app-shell.tsx:132`) — in a multi-child family on one device, whose gallery is this?; session death
  mid-scroll is a silent teleport to a bare login (`auth-guard.tsx:32`) with no "you were signed out". → A
  Change-password link in the footer; the student's name in the shell; a `?reason=expired` line on login.
- **R3-A4-09 · Low (bundled).** Hover-download scrim is hover/focus-only — effectively invisible on touch
  (`photo-tile.tsx:169`; lightbox Download covers it); chips ≈32px and tile buttons ≈32px tap targets;
  the event filter isn't in the URL; no offline cue (lead L16); "Download all" lives only at the top of a
  900-tile scroll; lightbox keyboard hints sr-only (lead L10).

### 4.5 The parent lens (uses the student account)

The student surface reads acceptably to a parent *until it's tested*: **"Only you can see these"**
(`me/events/page.tsx:175`, and "privately, just for you", `:164`) is structurally false — every teacher and
admin sees every photo (`permissions.py:25` `gallery:view_all`), admins additionally see per-photo download
history; and **face recognition is never explained** to the person whose face it is (grep
`face|recognition|privacy|consent` across the student/auth surfaces → zero rendered copy; the only mechanism
copy anywhere is staff-side). Each is one discovered contradiction away from converting reassurance into
caught-out overclaim — worse for trust than saying it plainly. Both are string-level fixes (R3-S5-02/03, §5.5).
Delivery being pull-only for a parent who won't log in weekly: *(parked: BP12)*.

---

## 5. Senior-PM cross-cutting analysis

### 5.1 The core-job trace (S1) — "the weakest hop is queued→worker"

Hop-by-hop (upload → process → ML → review → announce → see → save), judged on state-visibility, handoff,
failure recovery, and measurement. Verdict: **the core job completes on the happy path; the failure paths get
quieter the further they are from the event-detail page.**

- **R3-S1-01 · CRITICAL · P6/X5/X1 · capability — a stranded event is a permanent, invisible dead end.**
  If the event job permanently fails (5 nacks → DLQ — e.g. `EmbeddingVersionMismatch` nacks every delivery —
  or the job is lost with the stream; a mere worker crash self-heals via the queue's XAUTOCLAIM reclaim once a
  worker returns, `redis_streams.py:104-121`), the event stays in-flight forever: the UI says "Distribution is running — this
  updates automatically" (`events/[eventId]/page.tsx:583-584`) and polls eternally (`use-event-status.ts:18`);
  the Process button is hidden while in-flight (`:568`); the API refuses re-enqueue
  (`event_service.py:186` "event is already queued or processing"); the DLQ is written and acked with **no
  consumer anywhere** (`redis_streams.py:115-116,143`); no route, CLI, or ML-side path resets
  `processing_status` (the ML store only advances it). **No-workaround test: FE hidden / API 400 / archive
  doesn't touch it / no other writer / no DLQ tool — only out-of-band SQL.** Students never get the photos;
  staff has no lever and no signal. → An unstick path (Process allowed past an in-flight age threshold, or an
  admin reset) + a DLQ consumer that flips the event to a visible failed state.
- **R3-S1-02 · High · X5 — the failure half of the pipeline emits zero metrics.** Job metrics fire only on the
  ack path (`inference_worker.py:31`); nacks are a log line (`runner.py:104`); `photos_failed` is computed and
  never exported; no DLQ-depth, no queue-lag, no in-flight-age gauge (grep failure counters in both
  observability modules → 0). Even the stale-index "ALERT" is an unalertable log line (`runner.py:98`).
  → `jobs_failed_total{reason}`, DLQ depth, in-flight age.
- **R3-S1-03 · High · P2 — a stuck event is indistinguishable from a healthy one.** `enqueued_at` is delivered
  to the FE and rendered nowhere (grep → types.ts only); no elapsed-time, no threshold copy. After 2 hours the
  UI still asserts progress. → "processing since {t}" + escalation copy past a threshold.
- **R3-S1-04 · Medium · P1 — the second batch is invisible.** New photos on an already-completed event: the
  list pill still says "Completed" (raw `processing_status`, `events/page.tsx:590-591`), the dashboard alert
  predicate only catches never-processed events (`postgres_events.py:427-428`); the only nudge is the detail
  page the uploader must re-open. → Derive the list pill from counts (the detail page already does) + widen
  the alert.
- **R3-S1-10 · Medium · P2 — "All processed" over failed photos.** The dashboard's media summary has no
  `failed` field (`schemas/dashboard.py:82`), so 0 pending + 30 failed renders "All processed"
  (`dashboard/page.tsx:117`) — failed photos on unvisited events are lost silently (students in them never
  matched, nobody told). → Add `failed` + a needs-attention alert.
- **R3-S1-08 · Medium · X4/X1 — "saved" has data and no display.** Every save is recorded with its `event_id`
  (BP8b) and the server filter is wired (`audit.py:46-47`); no screen joins it back — per-event completion
  ("N of M saved") is invisible. → A Downloaded column on the roster or an event drill-in on the Access log.
- Also from the trace: the announce-without-review default (folded into R3-A3-08); "Notified N" honesty
  (R3-A3-07); the arrival-moment failures (R3-A4-02); upload interruption (R3-S3-05). Hops H8 (save) and the
  student-side H7 signal *mechanics* rate **ok** — the only fully-green hops.

### 5.2 IA, vocabulary + the design bar (S2)

- **R3-S2-01 · High · P10/D6 — the product describes its own pipeline in seven words.** Matching is "Process
  photos"/"Redistribute" (button) but "Distribution started." (toast, `events/[eventId]/page.tsx:362`) and
  "Distribution is running" (status); announcing is "Notify students"/"Auto-announce"/"Announced" — while the
  checklist says "Distribute to students" (`dashboard/page.tsx:235`), analytics says "Delivery rate … events
  announced" (`program-analytics.tsx:59-63`) and the estate column says "Distributed". An admin clicks
  "Process photos", reads "Distribution started.", and reasonably believes they've distributed — the checklist
  and alerts stay unlit until the *separate* Notify action. → One two-word grammar app-wide (e.g. **Match** /
  **Announce**), string-only.
- **R3-S2-05 · Medium · P9/D5 — the student surface still wears admin chrome (the R2 re-judge).** All roles
  render in the same `AppShell` (`auth-guard.tsx:47`): a w-60 white desktop sidebar carrying a single item,
  cool-gray tokens, an admin-white lightbox panel — vs the Pinterest bar's "warm chrome that gets out of the
  imagery's way". The grid itself now hits the bar; the wrapper doesn't. → A student layout variant (slim top
  bar, warm wash, `display-xl` hero) — token-level, no component churn.
- **R3-S2-02 · Medium · P1/D3 — the review scent dies one click early.** Dashboard alert → `/events` (generic)
  → find the pill → detail (where review is never mentioned) → View gallery → third tab; the tab isn't
  URL-addressable (`gallery/page.tsx:416`). The app's most differentiated capability is its
  hardest-to-reach. → `?tab=review` + deep-links + a detail-page chip (with R3-A3-08).
- **R3-S2-06 · Medium · D3 — category colors speak the status language.** The category palette reuses the
  exact success/warning/info pill classes (`lib/events/categories.ts:11-17` vs `status-pill.tsx:11-15`) — the
  hash can land a category (e.g. "Trip") on the exact warning amber, visually indistinguishable from "needs
  attention" in the same row. → A non-semantic hue set for categories.
- **R3-S2-03/04/07/08/09 · Medium.** The auth screen is brand-less (a student's *introduction* to the product
  is a gray card — `(auth)/layout.tsx:5-9`); the type ramp's top tier and the mono voice are dead tokens
  (`text-display-xl` and `font-mono` used nowhere — the temp-password dialog is the natural mono moment);
  the one "live" claim shows a **frozen spinner** (`Loader2` without `animate-spin`, `dashboard/page.tsx:92`);
  every tab/bookmark reads "Photo Distribution" (root metadata only); the product has three names ("Photos" /
  "Photo Distribution" / "My Photos"-vs-"Your photos") and its core noun three ("photos/media/items").
- **Bundled Lows:** stale "(soon) delegate" copy on classes (`classes/page.tsx:79` — delegation shipped);
  the school-status pill renders the raw lowercase enum (the only unmapped pill); the per-term analytics table
  is the one table outside the scrolling primitive (`program-analytics.tsx:94`); `photos/[mediaId]` — built
  deep-linkable in F5 — is reachable only from audit rows and the review lane (the Lightbox offers no
  permalink); estate "Enrolled" StatCard duplicates a hint; CSS-columns order the masonry column-major
  (chronology reads down, `unverified-runtime`).
- **IA verdicts:** breadcrumbs consistent (all 7 details); tabs semantics coherent; landings per role right;
  the 6-item school nav gives "Access log" a permanent slot while galleries/review have no nav presence —
  defensible, but the needs-review badge is the missing scent.

### 5.3 The feedback matrix (S3)

The full 40-mutation matrix (pending/success/failure/double-submit/confirm/undo per call site) was compiled;
the systematic holes:

- **R3-S3-11 · High · P2/P10 — one SWR flag freezes the product's signals.** (High for the student badge —
  the flagship delivery signal; the staff-side staleness alone would rate Medium.)
  `shouldRetryOnError: false, revalidateOnFocus: false` (`swr-provider.tsx:13`) + no intervals outside the
  event-status poll ⇒ every key fetches once per mount. The always-mounted shell therefore fetches the nav
  badges **once per session**: the student "new photos" badge — BP4's flagship — never lights in an open tab;
  staff dashboards/lists never see colleagues' changes; a transient blip converts any screen into a terminal
  error until a manual Retry. No as-of cue or refresh affordance exists anywhere (grep → 0). → Revalidate/poll
  the two badge keys + dashboard; an "Updated Ns ago" affordance.
- **R3-S3-05 · Medium · P6 — no long-op survives interruption.** Grep `beforeunload|navigator.onLine` → **0**
  across the app. Tab-close mid-batch (upload / bulk enroll / zip) aborts silently; SPA-nav leaves pools
  running headless — the bulk-enroll completion effects live in an unmounted component and never fire. *(Lead
  L16 absorbed.)* → A beforeunload guard on `isUploading || busy` + nav confirm on the upload page.
- **R3-S3-06 · Medium · P2/D7 — the staff download-all can report success on a partial (or empty) archive.**
  The gallery path toasts "Downloaded N" and exits select-mode without flagging n < selected
  (`gallery/page.tsx:58-63`) — the student page does this honestly (`me/events/page.tsx:42-47`), same op,
  different honesty; an all-fetches-fail run returns down the same path as user-cancel (`use-download-all.ts:55-56,71-76`).
  → Unify on the honest toast; distinguish cancel from zero-saved.
- **R3-S3-08/09/10 · Medium · P6/D6 — three misdirected error states.** Mid-session 401: the page shows
  "Something went wrong reaching the server" + a Retry that can never succeed (`auth-guard` only redirects on
  the cached `useMe` key). 422: FastAPI's array detail fails the string check → the one fixable error class
  says "Request failed" with no field info (`client.ts:29-32`). 429: the BFF strips every header but
  content-type — `Retry-After` never arrives (`route.ts:67`) — so a throttled school office reads as an
  outage, and the offered Retry re-spends the window. Also: 500s toast raw `str(exc)`
  (`main.py:105`) and backend jargon ("insufficient permissions") is toasted verbatim. → A shared 401
  interceptor; parse 422 arrays; forward + humanize 429.
- **R3-S3-01/02/03/04 · Medium.** Create-teacher is the one create that never refreshes its list
  (`staff/page.tsx:325` has no `onCreated` mutate — the roster shows the new teacher only after a reload);
  the invite dialog discards the one-time password on Esc/overlay with no "copied yet?" guard
  (`invite-result-dialog.tsx:47-50` — catastrophic for the student variant, feeding R3-A2-01; Medium where
  A2-02 is High because one dismissal loses one credential, not 500); resend-invite
  fires unconfirmed (§4.1); "This isn't me" has no confirm/undo and staff are never told a student disputed
  (§4.4).
- **Bundled Lows:** missing busy states on class-roster Remove and class-teacher X (double-fire flicker);
  silent success on the auto-notify toggle; Sign-out has no pending state; the category-delete confirm marks
  every row busy.

### 5.4 The a11y + mobile floor (S4)

The floor mostly **holds** — and several R2-era fears were positively refuted: every primitive has
focus-visible rings; no unlabeled icon-only button exists (inventory of ~70 `aria-label`/`ariaLabel` uses); FilterChips
is a real roving-tabindex radiogroup; dialogs trap correctly; tables have `overflow-x-auto` + `th scope`;
`aria-sort` is present; the reduced-motion guard is global and covers everything in use; all 21 error
EmptyStates carry `role="alert"` + direction. The breaks:

- **R3-S4-01 · High · D8 — sub-AA data text across every list.** `--color-ink-muted: #8890a0` computes to
  **3.21:1** on white (3.05 on surface) and its own token comment says "sub-AA as small text"
  (`globals.css:20`) — yet it styles every table header (`table.tsx:30`), StatCard label, LoadMore count,
  field hint, and trend label at 12px. The widest-blast floor break, and a one-primitive fix. → Swap
  data-bearing `text-ink-muted` → `text-ink-secondary` (5.89:1).
- **R3-S4-02 · Medium · D8 — the calendar has no responsive floor at all.** `grid-cols-7` with zero responsive
  classes inside an `overflow-hidden` card (`month-calendar.tsx:85-99`) ⇒ ~45px cells at 375px with truncated
  sub-24px stacked pills; the "today" badge is white-on-accent at **4.47:1** — the exact pair `button.tsx`
  deliberately avoids; `role="grid"` promises keyboard-grid semantics it doesn't implement. *(Lead L5.)*
  → `overflow-x-auto` + `min-w`, the darker accent, drop or honor the grid role.
- **R3-S4-03/04/05/06 · Medium.** Three links with no focus ring (the audit-row link + two estate links — the
  only three in the repo); the events bulk-select checkboxes are bare **16px** targets on a primary list
  (`events/page.tsx:537-543`; the toast dismiss likewise) while the students list has no checkbox column at
  all (lead L14 — the asymmetry); lightbox keyboard hints are sr-only-only and with a focused `<video>` the
  arrow keys **both seek and navigate** (`lightbox.tsx:70-77` window listener; documented in 0043); input
  resting borders are 1.54:1 on white (labels + focus ring mitigate — the "quiet input" tradeoff, flagged).
- **Bundled Lows:** no skip-link; auth layout lacks `<main>`; gallery alt text positional-only ("Photo 3 of
  41") with `alt=""` tiles — nothing richer exists to say (the staff upgrade: "students in this photo");
  `h3`-in-dialog without an h2; the 8-column events table is the heaviest mobile scroll; the at-cap tooltip is
  title-attribute-only; forced-colors mode untested (no static verdict possible).

### 5.5 Trust, privacy + the credential lifecycle (S5)

This product applies face recognition to children; its deepest asset is trust, and its copy keeps writing
checks the permission model doesn't cash:

- **R3-S5-02 · High · P7/D6 — "Only you can see these" is false.** (§4.5.) One line to fix: "Private to you
  and your school's staff — other students only ever see photos they're in too."
- **R3-S5-03 · High · P7/D6 — face recognition is explained to no one.** Zero "how this works" copy anywhere
  (grep across every surface); students trigger "This isn't me" against a system they were never told exists;
  staff correct confidence percentages nobody defined (what does 62% mean? when should I distrust it?);
  students can never see the reference photo of *themselves* the school enrolled (`students.py:186` is
  staff-gated). → One static "How photo matching works" page + a confidence legend.
- **R3-S5-04 · High · P7/D6 — the erasure dialog under- and over-tells.** "This removes the student's login,
  profile, and face enrollment." (`students/[studentId]/page.tsx:442`) — **untold destruction:** their entire
  matched-photo history and corrections are purged, unrecoverable (the R3-A2-01 chain); **untold survival:**
  the event photos containing the child's face stay in every gallery, and audit rows survive anonymized. Staff
  executing a parent's "remove everything" will believe this dialog did more than it did; staff using delete
  as a password reset will not know what they burned. → Copy that tells both sides.
- **R3-S5-06 · Medium · P7/X3 — sessions outlive their credentials.** Change-password rotates the hash but
  revokes no outstanding refresh token (no jti/version — `auth_service.py:61-77`); logout clears only this
  browser's cookies; there is no "sign out everywhere", no device visibility, and no copy telling a family on
  a shared computer that 14-day persistence is the default. Aggravator: **students can't even be disabled**
  (`students.py` has no status PATCH — BP7c covered staff/admins only), so the only session kill-switch for a
  student account is the lossy delete. → Minimally: honest login copy + revoke-on-password-change.
- **R3-S5-08 · Medium · P6 — the last-admin lockout isn't telegraphed.** Owner-accepted as
  platform-recoverable, but "Disable" toggles instantly with no confirm and no "this is the school's only
  administrator" check — the rollup knows the count (`schools/[schoolId]/page.tsx:172-181, 329`).
- **R3-S5-09 · Medium · D6 — the 30 MB cap hides exactly where it bites.** Disclosed on the reference-photo
  dialogs; absent on the event uploader — the only surface accepting **video**, where 30 MB ≈ seconds of phone
  footage — whose hint says "select as many as you like" (`upload/page.tsx:99`) and whose user learns per-file,
  after picking (`upload.ts:63`). → "Photos and videos up to 30 MB each."
- **R3-S5-11 · Medium · P7/D6 — the audit's two-sided honesty gap.** To admins it overclaims: "Every photo
  download in your school" (`audit/page.tsx:55`) — but recording is a client-side fire-and-forget fired only
  by the in-app save button; a right-click save on the rendered full-res URL records nothing, and views are
  never logged. To teachers it underclaims: nothing anywhere tells them their downloads are recorded and
  admin-visible — surveillance discovered, not disclosed. → One caption each side.
- **R3-S5-05 · Medium** — resend-as-reset undisclosed (merged §4.1); **R3-S5-07** — voluntary change-password
  unreachable (merged §4.4); **R3-S5-10** — the per-child audit pivot impossible (merged R3-A2-03).
- **Bundled Lows:** "Downloaded as" header is opaque; the CSV 500-row cap told only on rejection; no retention
  expectation set anywhere ("show up here" implies forever — copy only; retention itself parked BP16);
  "Removed from your photos" never says staff can restore it. **Positive:** the archive dialog is a model of
  honest copy ("Its photos are kept… You can restore it anytime").

### 5.6 Instrumentation + adoption honesty (S6)

The PM-question table: of nine questions an owner must answer, only **1 is answerable-good** (ever-opened
engagement) and 3 are answerable-but-misleading; the rest are **tracked-but-not-shown** (display gaps) or —
for teacher uploads, storage bytes, and login history — **not tracked at all** (capability). The risks,
evidence-ranked:

- **R3-S6-03 · High · X1 — "Delivery rate" measures the button, not the audience.** It's announced÷events
  (`analytics_service.py:71` "# announced") with archived events in the denominator; per-event opens
  (`seen_count`) exist and are **never aggregated or trended**. A school can show 100% delivery with 5% of
  rosters ever opened, and nothing on any screen contradicts it. The flagship claim is uninstrumented.
  → An audience-open-rate aggregate; rename or fix the card.
- **R3-S6-06 · High · X1/X2 — the accuracy ground truth is collected and never read.** Every confirm/reject/
  "not me" lands in `match_corrections` with verdict + timestamp (`db/models:533,545`); the only aggregate in
  the codebase subtracts from the review backlog (`dashboard_service.py:98-100`). "Is matching getting better
  or worse?" — the churn driver specific to this product — is unanswerable; a school losing faith produces a
  rising reject rate no one can see, while "needs review" *falls* as staff work harder, masking it. → Query-only
  verdict-rate aggregates → a Quality section. *(The model work is parked BP15; the metric is not.)*
- **R3-S6-04 · High · X4 — teacher attribution is a closing window.** Pricing hangs on `max_teachers`, yet:
  per-teacher last-login is stamped and unexposed; `events.created_by` is stored and appears in no schema or
  screen (grep → 0); **media has no uploader column at all** (`db/models:398-437`) — that history is
  unrecoverable retroactively. No renewal story, no accountability, no way to see the one teacher doing all
  the work. → Expose last-login + created_by now; add `uploaded_by` before more history is lost (small
  migration).
- **R3-S6-01/05/10 · Medium · X4 — activation and unit economics are dark.** Time-to-first-delivery is
  computable from existing timestamps and shown nowhere; the estate has no school-age or stalled-since axis
  (a 3-day and a 3-month stall look identical — S6-10); no bytes are tracked and no per-school media count
  reaches the platform (cost attribution impossible; the 30 MB videos are invisible).
- **R3-S6-02/07/08/09 · Medium.** "Ever saved" exists row-by-row (BP8b) with no distinct-savers aggregate;
  engagement is all-time-distinct — it literally cannot show decline (a monthly first-opens trend is one
  query-only mirror of `monthly_upload_counts` away); the student detail answers nothing about reach (the
  parent-phone-call workflow is ~120 roster visits — the data is two existing reads away); and **every rate
  card is a dead end** — no "which students" list behind any percentage, dashboard alerts land on unfiltered
  lists (`rate-card.tsx:35-56` renders no link; the students list has no signed-in/engaged filter).
- **R3-S6-11 · Medium — "Opened" resets on re-announce.** Roster `seen` is measured against the *latest*
  announce (`notification_service.py:217-221` — correct for the new-photos badge); staff read it as "who ever
  received event X", so a re-announce reports near-zero reach for an event most families already opened.
  → Add first-seen-based "ever opened" to the roster row.
- **Bundled Lows:** `/metrics` has no product-event counters; no client analytics SDK at all
  (privacy-consistent — but it makes the DB the *only* funnel instrument, raising the stakes on every display
  gap above); the trend labeled "Photos uploaded" counts videos; estate totals StatCards are vanity; the
  dashboard Photos StatCard links nowhere.

---

## 6. Cross-cutting themes

Round 2's themes were A–I; Round 3 continues the lettering. Each theme names the root cause behind findings
that would otherwise be fixed piecemeal.

| # | Theme | Roles hit | Lens | Gap type | Severity | Descends from |
|---|---|---|---|---|---|---|
| **J** | **Recovery has no path** — accounts were built provision-first, recover-never: no student credential path (the Critical), shown-once dialogs with no close-guards, resend-as-unconfirmed-reset, change-password unreachable, sessions unrevocable, students undisable-able, last-admin untelegraphed, the school record write-once | every role | P6/P7/X3 | capability | **Critical** | new |
| **K** | **The pipeline can strand, silently** — happy-path status model with no owner for stalls: the stranded event (Critical), zero failure metrics, no staleness cues, the invisible second batch, "All processed" over failed photos, interruption-blind uploads | staff, student (downstream), ops | P2/P6/X5 | capability | **Critical** | new (D-adjacent) |
| **L** | **The arrival moment doesn't land** — the receive surface got mechanics (BP3/9/17) but not the moment: inverted ordering, a banner that points at nothing, seen-burned-on-load, a frozen badge, the 60-chip wall, storyless photos, an unlabeled zip | student, parent | X1/P9/P5 | display | **High** | C (in-app half) + F |
| **M** | **The product misdescribes itself** — copy written from the system's side: seven words for one pipeline, "Notified N" over a log channel, "Only you can see these", face recognition unexplained, the erasure dialog's two silences, the audit overclaim, "Pending", misdirected 401/422/429 | every role | P10/D6/P7 | display (strings) | **High** | new |
| **N** | **The review loop is under-armed at the decision points** — no reference face beside the name, review debt invisible at announce (auto-announce default), the 5-hop scent, "This isn't me" unguarded with staff never told, accuracy metrics never read | teacher, admin, student | X2/P3 | display | **High** | H-adjacent |
| **O** | **Working blind at the desk** — BP14 built rates, not levers: announce≠reached, saved unaggregated, engagement can't decline, no teacher attribution (closing window), no activation/age axis, dead-end rate cards, the unrankable funnel | admin, platform | X4/P1/P8 | display | **High** | G |
| **P** | **One-way doors and interrupted work** — mutations designed forward-only: can't-clear tags (with silent "Other" preselect), confirm-only irreversible deletes, the manual CSV error loop, partial-download dishonesty (upload retry/interruption → K) | admin, teacher | P6 | mixed | **Medium** | E-adjacent |
| **Q** | **The floor's thin patches** — sub-AA data text everywhere (the one High), the unresponsive calendar, 16px targets, three naked links, sr-only-only hints, no URL state, no per-page titles, brand-less auth, frozen spinner, category-color collision, session-frozen data (→ L) | every role | D8/D2/P5 | display | **Medium** (one High: R3-S4-01) | D/F polish |

**J and K are the two Criticals** — and both are cheap relative to their severity: J's core fix is one
endpoint reusing proven BP7c machinery; K's is an unstick guard + a DLQ consumer + three counters. **M is the
highest leverage-per-effort theme in the review** (almost entirely strings). **L is the product's emotional
core** — everything R2 wanted for the student except the moment itself. **O is the owner's own dashboard.**

---

## 7. Grounding

### 7a. Evidence index (the load-bearing citations)

Every finding above carries its own file:line evidence inline; the claims the review leans on hardest:

- **No student credential path:** `services/backend/src/backend/api/routers/students.py` (full inventory 58–237,
  no credential route) · `staff.py:96` + `schools.py:131` (resend is staff/admin-only) ·
  `services/ml_service/src/ml_service/orchestration/enrollment.py:152` (delete purges matches) ·
  `inference.py:59,122-124` (worker skips completed → history unrebuildable).
- **The stranded event:** `services/backend/src/backend/services/event_service.py:186` (re-enqueue 400) ·
  `frontend/app/(school)/events/[eventId]/page.tsx:568,583-584` (button hidden; eternal copy) ·
  `services/ml_service/src/ml_service/adapters/queue/redis_streams.py:115-116,143` (DLQ written+acked, no consumer).
- **The frozen signal:** `frontend/components/swr-provider.tsx:13` · `frontend/components/ui/app-shell.tsx:156-157`
  (badges fetched once per session) · `frontend/app/(student)/me/events/page.tsx:129` (seen burned on mount) ·
  `services/backend/src/backend/adapters/repositories/postgres_media.py:165` (oldest-first).
- **Scope truth:** `frontend/app/(student)/me/events/page.tsx:164,175` vs
  `services/backend/src/backend/domain/permissions.py:25`.
- **Announce ≠ reached:** `services/backend/src/backend/services/analytics_service.py:71` ·
  `api/schemas/notifications.py:80-81` · `settings.py:90` (`notification_channels: str = "log"`).
- **The AA break:** `frontend/app/globals.css:20` (the token's own "sub-AA" comment) · `frontend/components/ui/table.tsx:30`.
- **Vocabulary:** `frontend/app/(school)/events/[eventId]/page.tsx:362,571-575` · `dashboard/page.tsx:235` ·
  `components/analytics/program-analytics.tsx:59-63` · `app/(platform)/estate/page.tsx:127`.

### 7b. Refuted leads (do not re-chase these)

A pre-review sweep alleged 25 rough edges; verification **refuted 11** with counter-evidence:

| Lead | Alleged | Counter-evidence |
|---|---|---|
| L1/L2 | /staff and /classes lack loading skeletons | both have the standard 3-row skeleton (`staff/page.tsx:328-331`, `classes/page.tsx:219-223`) |
| L3 | lightbox panel squeezes the image on mobile | it stacks: `flex-col sm:flex-row`, panel `max-h-[45vh]` (`lightbox.tsx:96,137`) — feel unverified-runtime |
| L4 | tables lack horizontal-scroll wrappers | the primitive wraps every table (`table.tsx:8`); one exception: the raw per-term table (`program-analytics.tsx:94`) |
| L11 | no `aria-sort` | present on every SortableHead (`sortable-head.tsx:31`) |
| L20 | status changes not SR-announced | an `aria-live` region mirrors the processing messages (`events/[eventId]/page.tsx:581`) |
| L21 | an event "Settings tab" (with delete + max-media) | no tabs exist on the event detail — edit is a dialog; no such fields |
| L22 | an event "Download history tab" | `DownloadHistory` is a per-photo, admin-only panel mounted on the photo page + lightbox |
| L23 | the audit table has an IP column | columns are When/Who/Photo/Downloaded-as; no IP is recorded (BFF hides the client IP, 0051) |
| L24 | "delete event" exists | archive only — no DELETE route (`events.py`) and no FE affordance, by design (0027) |
| L25 | no reduced-motion guard | global guard at `globals.css:108-116`; no JS-driven animation exists to escape it |

Confirmed: L5, L7, L8, L9, L12, L14, L15, L16, L19 · Partial: L10, L18 — absorbed into the findings above with
their evidence. L13 is the credential chain itself (R3-A2-01/02); L6's confirm-only deletes are covered by
R3-S5-04/A4-04 (undo-toasts consciously not proposed — see `07` BP24's "not included"); L17's back-nav
position loss rides in the R3-A4-09 Low bundle + `07` BP25 slice 8.

### 7c. Needs a live run (static-review limits)

The pending live smoke (`05` §D) should also cover, in rough priority: the lightbox's 45vh staff-editor panel
on a real phone · the 61-chip fold on a 375px screen · a killed-worker stall (R3-S1-01's runtime shape) · the
empty-zip path of an all-fail download-all · headless-pool behavior after unmount · masonry column-major order
perception · the video `#t=0.1` poster across browsers · forced-colors mode (no static verdict possible) ·
SR announcement timing where multiple live regions coexist · `EmailStr`-vs-browser email divergence (R3-S3-09's
reachability).

---

## 8. What this implies — over to the roadmap

Round 2 ended "the product can't be turned on, can't deliver, and organizes nothing." All three are gone.
Round 3's verdict is one sentence per theme:

- **J:** the product must be able to *give someone back in* without destroying why they came (one endpoint + four guards).
- **K:** every in-flight state needs an owner, an age, and an exit (an unstick, a DLQ consumer, three counters).
- **L:** the arrival moment should open on the new photos, name them, and stay fresh (ordering + banner links + two SWR flags).
- **M:** say what it does — one verb pair, true privacy claims, an explained matcher, honest dialogs (a strings pass).
- **N:** put the evidence where the decision is (a face in the review tile, the debt at the announce button).
- **O:** turn the rates the owner already has into levers (opens/saves aggregated, attribution before the window closes, lists behind every percentage).
- **P:** every door two-way (clearable tags, exportable failures, honest partials; upload retry rides with K).
- **Q:** one floor sweep (a token swap, a calendar minimum, URL state, titles, targets).

The build order — owner-delegated, effort×impact — lives in
**[`07-improvement-roadmap-round-3.md`](07-improvement-roadmap-round-3.md)** (BP18+). Parked items
(BP12/15/16, video timeline) remain parked in `05` and are untouched by this review.
