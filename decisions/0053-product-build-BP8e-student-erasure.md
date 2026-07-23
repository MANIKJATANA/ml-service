# 0053 — Product Build BP8e: Complete student erasure

**Date:** 2026-07-24
**Status:** Accepted

## Context

The final slice of **BP8 (Ops & reliability)** and the last of the whole **BP1–BP8** roadmap (`product/03`). Today
"delete a student" was **incomplete** — it removed the login/profile (cascading `match_corrections` +
`notification_reads`; `download_audit` → SET NULL) and the ML FAISS vectors + `student_reference_photos` URIs, but **three
things were orphaned**: the reference-photo **object in storage** (no `delete` on either service's storage port), the
ML-owned **`matches`** rows, and the ML **detection-audit** candidate rows naming the student. So a "deleted" student
still had data lingering. BP8e closes those three gaps so **delete means gone** — a real, verifiable erasure
(**trust/ops value, not legal/consent — that's out of scope**, `product/03` §4). **Cross-service (backend + ML); NO
migration, no new perm (`student:manage` gates it), no new env var.** Events stay archive-only (event hard-delete +
time-based retention were considered and **deferred** — owner picked the focused erasure).

## Decisions (ownership-split: BE erases storage + its own rows; ML erases its own tables)

The existing flow — `StudentService.delete_student` calls **ML-delete-first** (`MlEnrollmentClient.delete` →
`DELETE /v1/schools/{id}/students/{id}`) then deletes the login (cascading the profile) — is kept; each side is made
**complete**. **No change to the BE↔ML HTTP contract** (the ML DELETE endpoint just does more internally).

### 1. Backend — delete the reference-photo storage object (retry → best-effort)
`ObjectStore.delete(object_path)` is added to the port + both adapters — `SupabaseObjectStore`
(`storage.from_(bucket).remove([path])`, idempotent, `UpstreamError` on transport failure) and `LocalFsObjectStore`
(a no-op dev stub, since its uploads aren't real). `StudentService.delete_student` reads the `student` (which carries
`reference_photo_path`) **before** the cascade, so the path is in hand: `get_student` → **ML delete** → **delete the
reference-photo object** → **delete the login** (cascade). The object delete is `_delete_object_best_effort`: **retry up
to 3 attempts** (0.2s backoff) on `UpstreamError`, then log a loud, greppable `orphaned_reference_photo` **warning** and
**continue** — a leaked object is a storage cost, not a DB/privacy hole, so the erasure never hangs on a transient blip
(owner's chosen behaviour). Guarded on `reference_photo_path is not None` (a bulk-imported photoless student has nothing
to delete).

### 2. ML service — purge the student's `matches` + detection-audit rows
`MatchRepository.delete_by_student(school_id, student_id)` (`DELETE FROM matches WHERE school_id=? AND student_id=?`) and
`DetectionRepository.delete_candidates_by_student(school_id, student_id)` (`DELETE FROM face_detection_candidates WHERE
student_id=?` — only the student-naming candidate rows; the media-centric parents
`media_detections`/`media_frames`/`face_detections` stay, since they belong to the media, shared across students in a
group photo; `student_id` is a globally-unique UUID so no school-join is needed). `EnrollmentService.delete` is extended
to also call these two (after the existing `index.delete` + `reference_photos.delete`); its constructor gains the
`MatchRepository` + `DetectionRepository` ports, and `container.enrollment_service()` injects them (already built for the
inference service — reused, lazy postgres, no model load).

### 3. `match_corrections` + `notification_reads` need **no code** — the FK cascade handles them
Deleting the login cascades **two levels** (`users` → `students` `ON DELETE CASCADE` → `match_corrections.student_id` +
`notification_reads.student_id`, both `CASCADE`), so the erased student's corrections + seen-state are removed
automatically — proven by a gated real-Postgres test (the in-memory fakes can't model a two-level cascade). Other
students' corrections survive; `match_corrections.corrected_by` on them is `SET NULL` (the correction outlives its
author).

### Erasure surface after BP8e (documented)
**Deleted:** login + profile + `notification_reads` + the student's `match_corrections` (FK cascade); ML FAISS vectors +
`student_reference_photos` URIs + `matches` + detection candidates; the reference-photo **object** (retry/best-effort).
**Anonymized (not deleted):** `download_audit` rows survive with `subject_student_id` + `actor_user_id` `SET NULL` — a
deliberate BP8b choice (the audit outlives the subject; the PII link is severed). Honest limit.

## Verification

- **Backend:** ruff + mypy + unit tests — `delete_student` erases the reference-photo object (a `FakeObjectStore`
  records the path); a failing storage delete **retries 3× then best-effort** (the student is still fully deleted, a
  loud warning logged, no raise); a **photoless** student skips the object delete; the ML-delete-first contract is
  unchanged (an ML `UpstreamError` still 502s and deletes nothing). **Gated real-Postgres** (`test_student_erasure_
  cascades_and_anonymizes`, on a **throwaway** DB): a student delete cascades `notification_reads` + the student's
  `match_corrections` away and NULLs `download_audit` subject/actor — a second student's data untouched.
- **ML:** ruff + mypy + unit test — `EnrollmentService.delete` also purges matches + detection candidates (stub repos
  assert the calls). **Gated real-Postgres** round-trips (throwaway DB): `delete_by_student` purges one student's
  matches tenant-scoped (others survive); `delete_candidates_by_student` removes only the student's candidate rows (the
  media-centric parents + other students' candidates remain).
- **Gate:** BE + ML ruff + mypy + layering green; full suites pass. (Live end-to-end erasure smoke — a real Supabase
  object removal — noted pending a running stack, per prior FE phases.)
- **2× review→fix loop** (two agents), gate green after each — see the commit for the applied fixes.

## Follow-ups

BP8e completes **BP8** and the **BP1–BP8 roadmap**. Deferred (documented, per `product/03`): **event hard-delete** (a
real "delete event" purging its media rows + storage objects + matches/detections, reusing this same delete machinery)
and **time-based retention** (an admin-triggered or scheduled purge of old data). Optional erasure polish: a background
sweeper that retries logged `orphaned_reference_photo` objects; extending the ML DELETE to an **event-scoped** purge.
