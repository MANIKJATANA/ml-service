# 0062 — Product Build BP14: Program analytics & trends

**Date:** 2026-07-27
**Status:** Accepted

## Context

Round-2 roadmap ([`04`](../product/04-improvement-roadmap-round-2.md) §BP14, theme G / lenses T4/P8/X4):
every dashboard is a **point-in-time count**. Neither the school admin ("how did distribution go **this
term**? how many of 800 students have **ever signed in**? which events **reached** their audience?") nor the
platform admin ("which schools **adopted**, which **stalled**?") can see a rate, a trend, or a funnel — a
school that CSV-imported 800 students and **enrolled zero** looks identical on the estate list to a thriving
one. BP14 adds the rate + trend + funnel framing on top of the BP1/BP2 counting machinery.

Per the owner-approved plan (an HTML explainer + a decisions Q&A, 2026-07-27), three decisions: **trends =
derived from timestamps** (query-only — no snapshot table/job; trends cover timestamped things, "enrolled" is
a current funnel not a historical line); **add `users.last_login_at`** (one small migration, the only schema
change — powers "ever signed in"); **both tiers in one phase** (school analytics + platform estate funnel).

## Decision (BP14)

A pure **`AnalyticsService`** composing existing + a handful of new grouped aggregates into two reads, plus
**one migration** (`0016`, `users.last_login_at`) and two FE pages. **No ML change, no new permission, no new
dependency, no new env var.**

### Backend

- **Migration `0016`** — a nullable `users.last_login_at` timestamp, stamped `now()` on a successful login
  (`AuthService.login` → `UserRepository.touch_last_login`); **never on refresh** (not an interactive
  sign-in). No backfill (past logins weren't recorded → the rate is forward-looking from launch). The write
  is a direct Core `UPDATE` (no row load); `updated_at`'s `onupdate` also advances (harmless — it's internal).
- **School analytics** — `AnalyticsService.school_analytics(school_id)` composes: delivery (announced ÷ total
  events), sign-in (`count_signed_in_by_school_and_role(STUDENT)` ÷ total students), engagement
  (`count_distinct_seen_students` ÷ total students), per-term rollups, and a monthly upload/event trend.
  **Events + photos + per-term all derive from one `list_by_school` pass** (bounded ~120 events/yr) + the
  grouped `counts_by_event` scan — so the "announced" predicate stays identical to `count_distributed`
  (BP4), with no extra round-trips. Raw numerators/denominators flow to the FE (it renders the %). Route
  `GET /v1/analytics/school` (`dashboard:view`); tenant from the token, never the URL.
- **Estate analytics** — `AnalyticsService.estate_analytics()` composes per-school **cross-tenant grouped
  aggregates** (the BP2 `list_schools` pattern, zipped by `school_id` in-Python, no N+1): `role_counts` +
  `signed_in_role_counts` (users), `counts_by_school` + `enrolled_counts_by_school` (students), `counts` +
  `distributed_counts` + `recent_event_counts(since=now−30d)` (events). Per school: a funnel (staff →
  students → enrolled → events → distributed) + a **transparent heuristic** — `stalled` = students>0 &&
  enrolled==0 (the enrollment wall); `idle` = not stalled && enrolled>0 && no event created in 30 days.
  Route `GET /v1/analytics/estate` (`school:manage`, platform only).
- **New aggregates** (all grouped, one indexed scan each): `UserRepository.{touch_last_login,
  count_signed_in_by_school_and_role, signed_in_role_counts_by_school}`; `StudentRepository.
  enrolled_counts_by_school`; `EventRepository.{distributed_counts_by_school, recent_event_counts_by_school,
  monthly_event_date_counts}`; `MediaRepository.monthly_upload_counts`; `NotificationReadRepository.
  count_distinct_seen_students`. The monthly trend buckets **photos by upload `created_at`** but **events by
  their `event_date`** (when the event happened, not the row-create time — undated events excluded), each keyed
  `'YYYY-MM'` for a stable sort.
- The analytics VOs (`SchoolAnalytics`/`EstateAnalytics`/`SchoolFunnel`/`TermRollup`/`MonthPoint`) live in
  `analytics_service.py` (the `SchoolDashboard`-in-`dashboard_service.py` pattern) — minimal domain churn; the
  service stays import-pure (uses only `dataclasses` + `datetime`), so the layering invariant holds.

### Frontend

- **Program-analytics section IN the school Dashboard** (a `ProgramAnalytics` component in
  `(school)/dashboard`, school_admin + teacher — **no separate nav item/page**; owner call: keep it in the
  dashboard they already land on) — three `RateCard`s (delivery/sign-in/engagement, % derived once with a `—`
  for a zero denominator + a slim progress bar), a dependency-free `TrendChart` (CSS bars + a visually-hidden
  data table for SRs) for photos + events per month, and a per-term table. It fetches its own analytics
  (`useSchoolAnalytics`) so a load/error there never blocks the rest of the dashboard, and it renders only once
  the dashboard has data (the existing `!isEmpty` gate) — so a brand-new school sees the setup checklist, not a
  wall of "—". The dashboard's existing Students/Events/Photos `StatCard`s cover the totals, so the section
  adds only the rates/trend/per-term.
- **Estate health page** (`(platform)/estate`, its own path + platform nav item — the platform admin has no
  "dashboard" to fold into) — stalled/idle alert cards, estate-total `StatCard`s, and an adoption-funnel
  `Table` with a healthy/idle/stalled `StatusPill` per school, each row linking to `/schools/{id}`.

## Why

- **Reuse, don't rebuild.** The counts are the same grouped-scan pattern BP1/BP2 established; BP14 adds a few
  siblings + a pure composing service — which is why it needs only one tiny migration and no ML change.
- **Query-only trends** (the owner's call) keep it an M-phase: a snapshot table + rollup job would be the only
  way to get a true historical "enrolled over time" line, so that stays the documented scale-up and "enrolled"
  is shown as the current funnel instead.
- **Sign-in is the one real gap.** Every other signal already flows; a login timestamp didn't exist, so the
  one column + one-line write is the minimal honest way to answer "how many have ever signed in".
- **Transparent stalled heuristic**, not a model — a rule the operator can trust and we can tune.

## Security

- **Tenant isolation:** the school tier takes `school_id` strictly from the token (`tenant_of`), never the
  URL; every school-scoped aggregate is `WHERE school_id`. The estate tier's cross-tenant aggregates are
  reachable **only** behind `school:manage` (platform admin) — the same gate the schools list already uses.
- **Permissions unchanged:** school analytics = `dashboard:view` (admin + teacher), estate = `school:manage`
  (platform). A student/unauthorized → 403; no token → 401. No new permission.
- **The sign-in write** persists only a timestamp (never a credential) and only on a fully-authenticated
  login; refresh does not stamp.

## Alternatives considered

- **A daily/weekly snapshot table + rollup job** (true historical trends of any metric). Declined by the owner
  for v1 — heavier (a migration + a scheduler + ops surface) than the roadmap's M sizing; documented scale-up.
- **Outbound email/SMS delivery stats** (sends/bounces/opens). Out of scope — there's no email channel yet
  (BP12). "Delivery" here = in-app announced + seen (the signals BP4 writes).
- **A charting library.** Unneeded — the trend/bar visuals are plain CSS/SVG with a table fallback, so no new
  FE dependency.
- **Backfilling `last_login_at` / counting refresh as a sign-in.** Declined — we never recorded past logins;
  the rate is honestly forward-looking, and refresh isn't an interactive sign-in.

## Consequences

- **One migration (`0016`), no ML change, no new dependency, no new permission, no new env var.**
- **Honest limits (documented):** trends are derived from timestamps (no historical enrolled line — the funnel
  is current-state); `last_login_at` has no backfill (climbs from launch) and isn't stamped on refresh;
  per-term photos come from an events-pass + `counts_by_event` join in-Python (bounded ~120 events); engagement
  = distinct students who opened ≥1 distribution ÷ all students (coarse); the estate stalled/idle rule is a
  simple heuristic, not a model.
- **Verification:** BE ruff + mypy + **556 passed / 38 skipped** + layering; `test_bp14_analytics.py` (school
  rates/per-term/trend composition + tenant isolation + missing-school 404; estate funnel + stalled/idle +
  totals; login-stamps-not-refresh; the two routes' shape + permission gates 403/401 + a login→analytics
  sign-in-count e2e) + gated real-Postgres aggregate round-trips (`test_bp14_user_signin_aggregates`,
  `test_bp14_analytics_grouped_aggregates`) on a **throwaway** DB (`bp14_migtest`, dropped; dev `app`
  untouched). Migration `0016` up→down→up on the throwaway. FE tsc + lint + `next build` green. **2× review→fix
  loop** (both rounds returned 0 blockers), gate green after each: **R1** (correctness/security/tenant — all
  verified airtight) → made `touch_last_login` genuinely **best-effort** in `AuthService.login` (a metrics
  write can't fail a valid login), removed a misused `role="status"` on the estate alerts card, and
  locale-formatted the totals; **R2** (edges/quality/coverage) → treated a **blank/whitespace term** as
  untagged in `_term_rollups`, branched the zero-events "By term" copy, and added 4 tests (empty-school zeros,
  blank-term-untagged, the 12-month trend cap across a year boundary, and login-survives-a-`touch_last_login`-
  failure). No commit / push without an explicit request.
