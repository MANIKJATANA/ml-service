# 0033 — Frontend staff + students + enrollment (Phase F3)

**Date:** 2026-07-13
**Status:** Accepted

## Context

F2 ([0032](0032-frontend-platform-admin.md)) delivered the platform-admin surface. **F3 is the
first school-scoped feature area**: the `(school)` group's **staff** and **students** management,
including the **direct-to-Supabase reference-photo upload** and **synchronous ML enrollment** wired
to the backend from [0026](0026-students-and-ml-enrollment.md). It also cashes in the **one additive
backend change** reserved back in [0030](0030-frontend-architecture-and-design-system.md): `email` on
the students read model. Architecture is unchanged (BFF, client SWR, per-persona groups); this record
covers what F3 adds and refines.

## Decisions

### 1. Backend additive — `email` on the students read model (approved, additive, read-only)

The staff Students table/detail need the login email set at create time, but the `Student` read model
carried `name` and not `email`. Added `email: str` to the domain `Student`, to `StudentResponse`
(+ `from_student`), and had `PostgresStudentRepository` read it via an **inner JOIN** `students.user_id
== users.id` (safe: `user_id` is `NOT NULL` + FK `ON DELETE CASCADE`, so a student always has exactly
one user). `create` fetches the just-provisioned login's email with one scoped PK SELECT. **Purely
additive** — request bodies, enums, auth, ordering, and the create/enroll/delete flow are untouched;
`password_hash` stays unexposed. The test doubles mirror the JOIN (`FakeUserRepo.email_of` wired
through `SeededContainer`), and the tests assert the email end-to-end (normalized). **No migration**
(the column already exists on `users`; this only reads it).

### 2. Screens (`(school)` group — school_admin / teacher)

- **`(school)/staff`** — a `Table` of teachers (email + a single status pill: Active / Awaiting
  sign-in / Disabled) with a **Create-teacher `Dialog`** (email + visible temp password). Surfaces the
  backend **409** (`{detail}` distinguishes duplicate-email from the **teacher cap**) as an error toast.
  **school-admin-only** (see §4).
- **`(school)/students`** — a `Table` (StudentAvatar + name → detail link, email, enrollment pill) with
  a **Create-student `Dialog`** that runs the two-step upload→create flow (§3). Enrollment tone:
  enrolled→success, pending→warning, failed→error (shared map, §5).
- **`(school)/students/[studentId]`** — student detail (avatar header, email, enrollment pill, added
  date) with **Re-enroll** and **Delete** (via `ConfirmDialog`). 404 shown distinctly from a generic
  error. Delete invalidates both the `"students"` list and the `students/${id}` detail SWR keys, then
  navigates. A failed-enrollment note explains the likely cause + next step.

### 3. Direct-to-Supabase upload (`lib/api/upload.ts`)

`uploadReferencePhoto(file, onProgress)`: validate `image/*` → mint a signed URL via the BFF
(`POST /v1/students/upload-url`) → validate size against the response's `max_upload_mb` (30 MB
fallback) → **XHR PUT the bytes straight to the signed URL** (never through the BFF), reporting
progress. The bytes bypass Next entirely (the PUT targets the absolute Supabase URL). Hardening from
the review loop: an `xhr.timeout` (120 s) + `ontimeout` so a stalled PUT can't hang the dialog forever;
distinct messages for wrong-type / too-large / failed / timed-out. The create dialog **memoizes the
uploaded object path** — fixing a rejected field (e.g. a colliding email) and resubmitting does **not**
re-upload the same photo (the path is cleared when the chosen file changes). An orphaned object on a
create-after-upload failure is left to Supabase's lifecycle policy (documented, not cleaned up here).

### 4. `RoleGate` — staff is school-admin-only

Teachers hold `student:manage` but **not** `staff:manage` ([0024](0024-auth-jwt-and-rbac.md) RBAC), so
`/staff` is school-admin-only. The shell nav already omits Staff for teachers; to also cover a direct
URL hit, added `components/role-gate.tsx` — a lightweight gate for a single screen **inside** an
already-`AuthGuard`ed group. It renders no shell (the parent `AuthGuard` did) and, for a disallowed
role, redirects to the role's home. Because the shell only mounts children after `useMe` resolves, the
gated screen's data fetch never fires for a teacher. Used to wrap the staff screen.

### 5. New primitives + shared helpers (`components/ui`, `lib/`)

- **`avatar.tsx`** (`StudentAvatar`) — initials on `bg-surface-2` (restrained neutral, **not** the
  accent), with an optional `photoUrl` that swaps to `next/image` — so a real reference-photo thumbnail
  is a one-prop change when an endpoint exists (the F0 "avatar now, changeable" call).
- **`file-dropzone.tsx`** — controlled drag-or-click picker (parent owns the `File`) with a thumbnail
  preview. The object-URL is created via `useMemo` + a cleanup-only `useEffect` (revoke on change/
  unmount) — deliberately **not** setState-in-effect, which this repo's `react-hooks/set-state-in-effect`
  lint rule rejects. Keyboard-operable (`<label>` + focusable `sr-only` input).
- **`progress-bar.tsx`** — determinate bar (`accent-hover` fill) with `role="progressbar"` + an
  `aria-label`/`aria-valuetext`; the create dialog pairs it with an `aria-live="polite"` percentage.
- **`confirm-dialog.tsx`** — controlled confirm (no trigger) reusing `Dialog`; destructive variant.
- **`lib/students/enrollment.ts`** — single source of truth for enrollment `ENROLL_TONE` + `ENROLL_LABEL`
  (capitalized pill labels), shared by the list and detail screens.

### 6. Error UX asymmetry (enroll vs delete)

Confirmed against the backend: **re-enroll never 502s** — `enroll_student` catches ML failures and
returns **200 with `enrollment_status="failed"`**, which the UI surfaces as a warning ("Enrollment
still failed."). **Delete does propagate 502** (`_ml.delete` is not caught). The handlers and comments
reflect this: re-enroll's `catch` is only for 404 / expired-session / network.

### 7. Data layer

`types.ts` gains `EnrollmentStatus`, `StudentResponse` (incl. `email`), `UploadUrlResponse`;
`endpoints.ts` gains `listStaff`/`createStaff`, `listStudents`/`getStudent`/`createStudent`/
`enrollStudent`/`deleteStudent`/`studentUploadUrl` (path params `encodeURIComponent`-encoded);
`lib/hooks/{use-staff,use-students}.ts` (`useStaff`, `useStudents`, `useStudent(id)` — keys `"staff"`,
`"students"`, `"students/${id}"`).

## Alternatives rejected

- **A shared `CreateEntityDialog`** for the teacher/student dialogs — the student one adds name + upload
  + progress + a two-step submit; at N=2 the slots/render-props cost more than the ~40 shared lines save
  (same call as [0032](0032-frontend-platform-admin.md)). Revisit at a third.
- **Threading the email down from `StudentService.create`** instead of the extra SELECT — would change
  the service flow; the "purely additive" constraint favored a single indexed PK read in the repo.
- **Whole-row-clickable students table** — the row keeps F2's `hover:bg-surface` with only the name as
  the focusable link (consistent with the schools table); row-level click + keyboard is more work and
  generally discouraged.
- **Reverting the dropzone to setState-in-effect** for the object URL — cleaner-looking but fails the
  repo lint rule; `useMemo` + cleanup effect is correct and Strict-Mode-safe.

## What this phase does NOT do (deferred, documented)

- **Live smoke not run** — Docker Desktop (backend + DB + Supabase path) was down when F3 landed. The
  one thing static review can't confirm is the **Supabase signed-upload PUT + Content-Type** contract
  between `upload.ts` and the backend's `SupabaseObjectStore`; **run the create-student + upload +
  enroll + delete smoke once the stack is up.**
- No real reference-photo thumbnail yet (avatar `photoUrl` is wired but unused — needs a backend
  read-signed-URL endpoint); no orphaned-upload reaping (Supabase lifecycle); mobile nav drawer (still,
  from F1); long name/email truncation is by cell only.

## Testing

- Gate green (`eslint` + `tsc --noEmit` + `next build`, Node 22) after each review round; backend gate
  green (ruff + mypy + `234 passed / 11 skipped`).
- **2× review→fix loop.** R1 (correctness): backend `email` audit — no blockers (JOIN safe, additive,
  behavior-preserving). FE — no blockers; fixed the misleading re-enroll "502" comment (ML-down is 200
  `failed`), added detail-cache invalidation on delete, kept the list pill in sync after re-enroll, and
  added `RoleGate` after confirming teachers lack `staff:manage`. R2 (design/a11y/edge): design fidelity
  — highly faithful, no breaks; added the upload **timeout**, ProgressBar accessible name + live %,
  RoleGate spinner (not blank), **upload memoization**, cross-action button disabling, capitalized pill
  labels + hoisted `ENROLL_TONE`, and bumped the failed-enrollment note to `text-ink-secondary` (AA).
- Live smoke **pending** the backend (above).

## Files

- **New:** `app/(school)/students/[studentId]/page.tsx`; `components/role-gate.tsx`;
  `components/ui/{avatar,file-dropzone,progress-bar,confirm-dialog}.tsx`; `lib/api/upload.ts`;
  `lib/hooks/{use-staff,use-students}.ts`; `lib/students/enrollment.ts`.
- **Changed (FE):** `app/(school)/{staff,students}/page.tsx` (were F1 placeholders);
  `lib/api/{types,endpoints}.ts`.
- **Changed (backend, additive):** `domain/models.py`, `api/schemas/students.py`,
  `adapters/repositories/postgres_students.py`, `tests/{backend_fakes,test_student_service,
  test_student_routes}.py`. **No migration.**
