# 0019 — Dev-only browser test UI for enroll + identify

Date: 2026-07-06

## Context

We wanted to hand-test the real ML pipeline from a browser: upload a reference
photo (it should land in Supabase and get embedded into the per-school index),
then upload a second photo and have the service name the student. The production
surfaces don't support this directly: enrollment is student-id-triggered and
resolves photo URIs the backend already stored (decisions/0009), and inference is
async/queue-driven and writes match records to the DB rather than returning names.

## Decision

Add a **dev-only** test harness, gated behind `ML_ENABLE_TEST_UI` (default
`false`; compose sets it `true` for local). It reuses the real composition-root
`Container`, so it exercises the real adapters (Supabase, Postgres, FAISS,
InsightFace), not mocks.

- `api/routes/dev_ui.py` (mounted only when the flag is on; named `dev_ui`, not
  `test_ui`, so pytest does not collect it):
  - `GET /test` — a single self-contained HTML page (no build step, no FE/BE).
  - `POST /v1/test/enroll` — uploads the photo to the media store, then calls
    `EnrollmentService.enroll(school_id, student_id, [uri])`, which fetches it
    back and upserts the embedding. Proves the Supabase round-trip.
  - `POST /v1/test/check` — detects + embeds the uploaded photo in-memory,
    `VectorIndex.search`, and runs the same `apply_threshold_and_gap` decision as
    the worker, returning the matched `student_id`. Synchronous read; no DB write,
    no queue.
  - `POST /v1/test/check-bulk` — same identify path over many uploaded files in
    one request; returns a per-file result (in upload order) so the UI shows each
    image next to its identified student. Reuses one `_identify_image` helper.
- `MediaStore` adapters gain an `upload(object_path, data, content_type)` helper
  (Supabase + local_fs). It is **not** added to the `MediaStore` port — only the
  test UI uses it (typed via a local `_Uploadable` Protocol).
- New dep `python-multipart` (FastAPI needs it for `File`/`Form`).
- `student_id` *is* the student's name in this service (no separate name table);
  `school_id` defaults to `test-school`.

## Notes / rejected

- Not routed through FE/BE (still shells) — the goal was a quick, self-contained
  test against the service the user already runs in Docker.
- Off by default and `include_in_schema=False` so it never leaks into prod docs.
- Must run inside the ML image (InsightFace is Linux-only), which the compose
  `ml-service` container already is.
- Easy to remove wholesale (one module + one flag + the `upload` helpers) if a
  real FE/BE flow supersedes it.
