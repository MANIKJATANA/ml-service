# 0050 — Product Build BP8b: Access / download audit

**Date:** 2026-07-23
**Status:** Accepted

## Context

The second slice of **BP8 (Ops & reliability)** (`product/03`, sliced a–e; BP8a was [0049](0049-product-build-BP8a-failed-photo-retry.md)). Fails lens **T7/X5**: the backend mints a short-lived signed download URL for any entitled caller (`GalleryService.download_url` → `GET /v1/media/{id}/download`) and kept **no record** — a school-admin couldn't answer "who downloaded this student's photo, and when?" This is a **trust** feature, **not compliance** (consent/legal is out of scope, `product/03` §4). **Backend + frontend; one migration (`0010`); no ML change** — a backend-owned append-only table, no cross-seam SQL join. Mirrors the BP5 `match_corrections` structure (VO + port + postgres adapter + registry/container + gated real-PG test).

Owner scope calls (this session): **downloads only** (not gallery view-URL mints — a per-tile hot path); **both** read surfaces (per-photo history + a school-wide log); a **new dedicated `audit:view` permission**, **school_admin only** now, designed so adding teachers later is a one-line `ROLE_PERMISSIONS` edit.

## Decisions

### 1. A `download_audit` table (migration `0010`), append-only
`school_id`/`media_id`/`event_id` FKs → **CASCADE** (`event_id` denormalized from `media.event_id` — safe, media→event is immutable); `actor_user_id` → `users.id` **SET NULL** (a deleted account must not erase the log row); `actor_role` **String not null** with a `CHECK` lockstep with `Role` (denormalized so the log still shows *who, in what capacity* after the account is gone); `subject_student_id` → `students.id` **SET NULL**, nullable (the student's own id on a self-download; NULL for staff); `created_at`. **No `updated_at`** — rows are immutable. Four composite indexes (`created_at` trailing each) serve the per-photo history + the school-wide log + its event/student filters. New `DownloadAuditEntry` VO + `DownloadAuditRepository` port (`record` + `list_for_media`/`count_for_media` + `list_recent`/`count_recent`) + a postgres adapter; the reads order **`created_at DESC, id DESC`** (`id` a stable tiebreaker so same-instant rows never reorder across pages).

### 2. The write — a **separate** download action (`POST`), NOT the view mint
The signed-URL mint (`GET /v1/media/{id}/download` → `download_url`) is used for **both viewing and downloading** — `SignedImage` renders every grid tile / lightbox / photo detail off that same URL — so it **records nothing** (else every view would log a bogus "download", the bug this corrects). Recording moves to a dedicated **`POST /v1/media/{id}/download`** → `GalleryService.record_download`, which the frontend fires **only on the actual save** (a real download). It runs the **same entitlement gate** as the mint (a shared `_require_downloadable` — staff any in-school, a student only media they effectively appear in, else 404 with **nothing** recorded), then writes the row: `event_id` from the immutable media, `actor_user_id`/`actor_role` from the `CurrentUser`, `subject_student_id` = the `GalleryDownloadScope`'s `restrict_to_student_id` (the student's own id on a self-download; None for staff). The **frontend calls it fire-and-forget** (`recordDownload` in `useDownloadToDisk` + `useDownloadAll`), so a failed/denied audit never delays or blocks the download; on success it revalidates the per-photo download-log so an open history panel updates live. *(Download-all / BP3 client-zip records one row per saved media — correct, these are real downloads.)*

### 3. The reads — a read-only `AuditService` + `audit.py` router, `audit:view`
`AuditService` composes display data (actor email, event/student names) in-Python, batched — `media_download_history` (404 if the media isn't in the caller's school) and `school_download_log` (paginated, newest-first, optional event/student filters). Routes `GET /v1/media/{id}/download-log` + `GET /v1/audit/downloads?limit=&offset=&event_id=&student_id=`, both behind `require_permissions(Permission.AUDIT_VIEW)`, **tenant strictly from the token** (`tenant_of`, never the URL). `AUDIT_VIEW` is added to **`SCHOOL_ADMIN`'s frozenset only** — the deliberate one-line difference from the otherwise-identical teacher set. Page size is a module constant (default 50, max 200) — **no new env var**.

### 4. Frontend — school-admin-only, two surfaces
A `DownloadHistory` panel on the staff photo detail + lightbox: **self-gates** to `school_admin` via `useMe` (renders nothing + fires no `audit:view` fetch for a teacher/student — defense in depth over the backend RBAC), collapsed by default, the count on the toggle. A new **`(school)/audit`** "Access log" page (nav entry school-admin-only, `RoleGate allow={["school_admin"]}`) — a clean **server-paginated** table (When / Who / Photo→detail link / Downloaded-as) with Prev/Next + "Showing X–Y of N". A deleted actor reads "Removed account" with the role still shown. New `formatDateTime` util.

## Honest limits (documented)

- **`AuditService._compose` lists the full school roster of students + events per call** (`list_by_school`) to join names — bounded, admin-only, low-frequency, and consistent with `GalleryService`'s in-Python-join house style; a `list_by_ids`-keyed fetch is the scale-up if a school grows to thousands of students.
- **The school-wide log has no filter UI in v1.** The server-side **event/student filters are wired end-to-end** (repo → service → route → hook → endpoint) and reserved for a future per-event/per-student "downloads" drill-in; a client-side role-chip filter was **removed after review** because it filtered only the current page while pagination + totals were server-side (a misleading "Showing X–Y of N"). The per-photo history covers the media-scoped view.
- **Only download *intent* is recorded** — the signed-URL mint, not the byte transfer (which goes client→Supabase). Standard for this signed-URL model.

## Verification

- **Migration `0010` verified up→down→up on a throwaway Postgres** (`bp8b_migtest`, dropped; dev `app` DB untouched) — the table, all 4 indexes, the `actor_role` CHECK, and all 5 FKs (3 CASCADE + 2 SET NULL) confirmed; `down_revision "0009"`.
- BE gate green: ruff + mypy + **full suite 368 passed / 24 skipped** — incl. **the view/mint (`download_url`) records nothing** while `record_download` records the right row for staff (subject None) vs student self-download (subject = student.id), a **blocked download 404s + records nothing**, and the route-level proof that **N GET-views record 0** but a POST records (`test_view_does_not_record_only_the_download_action_does`); plus `AuditService` composition + tenant 404 + pagination + deleted-actor/subject degradation, and the read-route entitlement (**school_admin 200; teacher/student 403; unauth 401**). **Gated real-Postgres** `download_audit` round-trip (record → list/count → filters → pagination → newest-first ordering → tenant-safe) green on a throwaway DB.
- FE gate green: `tsc --noEmit` + `eslint` + `next build` (the `/audit` route + the panel).
- **2× review→fix loop** (two agents). **R1 (correctness/security/tenant): no blocker, no security or tenant bug** — the entitlement gate, tenant isolation (repo + service + route), best-effort write, and migration/ORM parity all verified clean; caught the missing **stable sort tiebreaker** (fixed → `created_at DESC, id DESC`). **R2 (edge/quality/a11y/UX): no blocker** — caught the **misleading client-side filter chips** under server pagination (removed → clean server pagination) and the **missing PG ordering assertion** (added); plus the error-note `role="alert"` and `Query()` annotations. Both confirmed ship-ready.

## Follow-ups

**BP8c** rate limiting (+ security headers) · **BP8d** multi-replica enrollment (Redis-lock Option B) · **BP8e** retention/erasure (per `product/03`). Optional BP8b polish: a per-event/per-student "downloads" drill-in wiring the reserved server-side filters; a `list_by_ids`-batched `_compose`; a `download_audit` Prometheus counter.
