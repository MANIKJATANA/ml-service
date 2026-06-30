# 0009 — Enrollment contract & the ReferencePhotoRepository port

**Date:** 2026-07-01
**Status:** Accepted

## Context

The owner specified the real enrollment flow: the **frontend uploads a reference
image directly to storage**, the **backend records its URL**, and for **enrollment
or refresh the backend sends the `student_id`** — the ML service then looks up that
student's reference-photo URL(s) from a table and fetches the image(s) itself.

Requirements §9 lists eight ports and the architecture §2 sequence draws the
photos arriving *in the request body*. The owner's contract instead makes
enrollment **student-id-triggered**, with the ML service resolving URIs from its
own store. Per the CLAUDE.md rule, this divergence is recorded rather than applied
silently.

## Decision

- **Enrollment is student-id-triggered.** `EnrollmentService.enroll(school_id,
  student_id, photo_uris=None)`:
  - if `photo_uris` is given, replace the student's stored URIs first (register);
  - otherwise use the URIs already stored (refresh);
  - fetch each URI via `MediaStore`, detect, pick the largest face, embed, and
    upsert all embeddings as one atomic replace (FR-E3).
- **A ninth port, `ReferencePhotoRepository`** (`get` / `replace` / `delete` of a
  student's photo URIs), backs this. It is analogous to `ThresholdProvider`:
  business state the service reads through a port. The ML service owns a
  `student_reference_photos` table (created via an Alembic migration in Phase 2),
  so it never reads the core system's schema (keeps tenant isolation + decoupling;
  the ML service never calls the backend).
- **Media is fetched through `MediaStore`** — the same port the inference path
  uses — defaulting to Supabase Storage (the storage choice itself is recorded
  with the Phase-2 adapter work).
- **HTTP shape (Phase 3):** `POST /v1/schools/{school_id}/students/{student_id}/enroll`
  with an optional `{photo_uris: [...]}` body; `DELETE` of the same path removes
  embeddings + stored URIs (FR-E2).

## Why

- Reuses the existing media abstraction (NFR-2) instead of adding a separate
  upload ingestion path; keeps the synchronous enroll request small.
- One endpoint covers both enroll and refresh, matching the owner's wording.
- The service still consumes photo *bytes* internally, so switching to multipart
  upload later (if the backend ever has no durable URL) is a route-only change.

## Alternatives rejected

- **Multipart upload of bytes in the request** (architecture §2's literal draw) —
  heavier API, doesn't match "BE sends the student_id; ML fetches from the table".
- **ML reading the backend's `students` table directly** — couples ML to the
  core's schema and breaks the "ML never depends on BE" rule.

## Follow-ups (later phases)

- Phase 2: `student_reference_photos` migration + a Postgres `ReferencePhotoRepository`
  adapter; the Supabase `MediaStore` adapter.
- Phase 3: the enrollment API route + how the backend registers URIs.

## Known consideration

On re-enroll, the stored reference-photo URIs are replaced *before* embedding, but
the index upsert is skipped when **every** new photo fails to embed (we never wipe
prior vectors on an all-fail, FR-E3). So the stored URIs can transiently diverge
from the index's embeddings — new URIs recorded, old vectors retained. A later
option is to replace the URIs only after ≥1 embedding succeeds.

## Round-2 amendment (2026-07-01) — empty `photo_uris` is rejected

An explicitly empty `photo_uris=[]` is rejected with `EnrollmentError`, checked
*before* the `replace()` call so the stored URIs are never silently wiped. Clearing
a student's enrollment is `delete()`'s job (FR-E2), not enrollment's; `enroll(...,
photo_uris=None)` still means "refresh from the stored URIs". The fetched URI list
is also de-duplicated order-preserving so the same photo is never embedded twice.
