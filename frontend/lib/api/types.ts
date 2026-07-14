/**
 * TypeScript mirrors of the backend's request/response shapes and enums
 * (hand-maintained; the surface is small and stable — decisions/0030). Grown
 * per phase as new endpoints are consumed.
 */

export type Role = "platform_admin" | "school_admin" | "teacher" | "student";
export type UserStatus = "active" | "disabled";
export type SchoolStatus = "active" | "suspended";
export type EnrollmentStatus = "pending" | "enrolled" | "failed";

/** The one user shape the API exposes (GET /v1/auth/me + onboarding responses). */
export interface UserResponse {
  id: string;
  email: string;
  role: Role;
  school_id: string | null;
  status: UserStatus;
  must_change_password: boolean;
  created_at: string; // BP2: staff "added" date + admin roster
}

/** A school (platform onboarding — decisions/0025). Timestamps are ISO strings. */
export interface SchoolResponse {
  id: string;
  name: string;
  max_teachers: number;
  status: SchoolStatus;
  created_at: string;
  updated_at: string;
}

/** A student profile (decisions/0026); `email` is the linked login's (decisions/0033). */
export interface StudentResponse {
  id: string;
  school_id: string;
  name: string;
  email: string;
  reference_photo_path: string;
  enrollment_status: EnrollmentStatus;
  created_at: string;
  updated_at: string;
}

/** A schools-list/detail row: the school + its rollup (BP2, decisions/0039). */
export interface SchoolRollup {
  admins: number;
  teachers: number;
  students: number;
  events: number;
}
export interface SchoolWithRollup extends SchoolResponse {
  rollup: SchoolRollup;
}

/** A students-list row: the student + how many photos/events they appear in (BP2). */
export interface StudentListItem extends StudentResponse {
  appearance_count: number;
  event_count: number;
}

/** A short-lived direct-to-Supabase upload target (the token is inside `upload_url`). */
export interface UploadUrlResponse {
  upload_url: string;
  object_path: string;
  max_upload_mb: number;
}

export type EventStatus = "active" | "archived";
export type EventProcessingStatus = "not_started" | "queued" | "processing" | "completed";
export type MediaType = "image" | "video";
export type MediaProcessingStatus = "pending" | "completed";

/**
 * An event whose media is distributed to appearing students (decisions/0027).
 * `status` is the lifecycle (active/archived); `processing_status` is the event-level
 * inference state the FE polls. `event_date` is an ISO date (YYYY-MM-DD); the rest are
 * ISO datetimes.
 */
export interface EventResponse {
  id: string;
  school_id: string;
  name: string;
  description: string | null;
  event_date: string | null;
  status: EventStatus;
  processing_status: EventProcessingStatus;
  enqueued_at: string | null;
  completed_at: string | null;
  auto_notify: boolean; // BP4: auto-announce to students on completion
  notified_at: string | null; // BP4: last manual "Notify students" push
  created_at: string;
  updated_at: string;
}

/** An events-list row: the event + its counts (BP2, decisions/0039). */
export interface EventListItem extends EventResponse {
  media_count: number;
  matched_students: number;
  needs_review: number;
}

/** One uploaded event photo + its per-photo processing state (decisions/0027). */
export interface MediaResponse {
  id: string;
  school_id: string;
  event_id: string;
  storage_path: string;
  media_type: MediaType;
  processing_status: MediaProcessingStatus;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

/** The event-level status the FE polls + a per-photo breakdown (decisions/0027). */
export interface EventStatusResponse {
  event_id: string;
  processing_status: EventProcessingStatus;
  pending: number;
  completed: number;
  total: number;
}

/** A photo in a gallery — metadata only; fetch bytes via the download endpoint (0028). */
export interface GalleryMediaResponse {
  media_id: string;
  event_id: string;
  media_type: MediaType;
}

/** A student who appears in an event + how many of its photos they're in (0028). */
export interface StudentInEventResponse {
  student_id: string;
  name: string;
  media_count: number;
}

/** An event a student appears in + how many of its photos they're in (0028). */
export interface EventForStudentResponse {
  event_id: string;
  name: string;
  event_date: string | null;
  media_count: number;
}

/** A staff/student correction verdict over an ML match (BP5, decisions/0042). */
export type MatchVerdict = "confirmed" | "rejected" | "added";

/** A student who appears in one photo + that match's decision facts + the correction
 *  verdict (BP5). `verdict` null = an uncorrected ML match ("pending"); `confidence` null =
 *  an `added` (staff-added) student with no ML score. */
export interface MediaAppearanceResponse {
  student_id: string;
  name: string;
  confidence: number | null;
  needs_review: boolean;
  verdict: MatchVerdict | null;
}

/** One photo's ambiguous, unresolved matches — the staff review lane (BP5). */
export interface MediaReviewCandidate {
  student_id: string;
  name: string;
  confidence: number;
}
export interface MediaReviewResponse {
  media_id: string;
  event_id: string;
  media_type: MediaType;
  candidates: MediaReviewCandidate[];
}

/** A short-lived signed URL to fetch one media's bytes (0028). */
export interface DownloadResponse {
  download_url: string;
  expires_in_s: number;
}

/**
 * The admin command-center rollup (BP1, decisions/0038). Every count is read live from
 * the backend's own rows (and the ML `matches` seam) — there is no stored aggregate.
 * `needs_attention` mirrors the "do something" signals the dashboard turns into alerts.
 */
export interface DashboardResponse {
  school_name: string;
  students: { total: number; enrolled: number; pending: number; failed: number };
  events: { total: number; active: number; archived: number; processing: number };
  media: { total: number; pending: number };
  needs_attention: {
    events_undistributed: number;
    enrollment_failures: number;
    needs_review: number;
  };
}

/** The student's "new photos" signal (BP4, decisions/0041): an unseen tally + the
 *  announced events (newest first). Authoritative + cross-device. */
export interface MyNotificationEvent {
  event_id: string;
  name: string;
  event_date: string | null;
  media_count: number;
  unseen: boolean;
}
export interface MyNotificationsResponse {
  unseen_count: number;
  events: MyNotificationEvent[];
}

/** The result of a staff "Notify students" push. */
export interface NotifyResultResponse {
  notified: number;
}

/** The staff "who's been notified / seen" roster for one event (BP4). */
export interface NotificationRosterStudent {
  student_id: string;
  name: string;
  media_count: number;
  seen: boolean;
}
export interface NotificationRosterResponse {
  announced: boolean;
  auto_notify: boolean;
  notified_at: string | null;
  notified_count: number;
  seen_count: number;
  students: NotificationRosterStudent[];
}

/** What the BFF login handler returns to the browser — never the tokens. */
export interface LoginResult {
  must_change_password: boolean;
}

/** The backend's uniform error body ({"detail": "..."}). */
export interface ApiErrorBody {
  detail: string;
}
