/**
 * TypeScript mirrors of the backend's request/response shapes and enums
 * (hand-maintained; the surface is small and stable — decisions/0030). Grown
 * per phase as new endpoints are consumed.
 */

export type Role = "platform_admin" | "school_admin" | "teacher" | "student";
export type UserStatus = "active" | "disabled";
export type SchoolStatus = "active" | "suspended";
export type EnrollmentStatus = "pending" | "enrolled" | "failed";
/** Why an enrollment failed (BP7b) — the FE maps it to a specific explanation + fix. */
export type EnrollmentFailureReason = "no_face" | "ml_unavailable" | "error";

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

/** A provisioned/re-invited staff or admin account + its ONE-TIME temp password (BP7c).
 *  Returned by create-teacher / add-admin / resend-invite; shown once, never again. */
export interface ProvisionedUserResponse {
  user: UserResponse;
  temp_password: string;
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
  reference_photo_path: string | null; // BP7d: null for a photoless (bulk-imported) student
  // BP17: a backend-generated display thumbnail (null when photoless / generation failed).
  // The avatar requests ?size=thumb only when set, else the full-res photo.
  reference_photo_thumbnail_path: string | null;
  enrollment_status: EnrollmentStatus;
  enrollment_failure_reason: EnrollmentFailureReason | null; // BP7b: set when failed
  // BP11a: the class this student belongs to (null = un-classed); name denormalized for display.
  student_group_id: string | null;
  student_group_name: string | null;
  created_at: string;
  updated_at: string;
}

/** A class / section — the organizing unit for students (BP11a, decisions/0058). */
export interface ClassResponse {
  id: string;
  school_id: string;
  name: string;
  grade: string | null;
  section: string | null;
  created_at: string;
  updated_at: string;
}

/** A classes-list row: the class + how many students are in it. */
export interface ClassListItem extends ClassResponse {
  student_count: number;
}

/** The classes list (unpaginated — bounded per school; also feeds the students filter). */
export interface ClassListResponse {
  items: ClassListItem[];
}

/** A newly created student + its ONE-TIME server-generated temp password (BP7d). */
export interface ProvisionedStudentResponse {
  student: StudentResponse;
  temp_password: string;
}

/** One CSV row's outcome from a bulk import (BP7d). `status`: created | duplicate |
 *  invalid | error; `temp_password` set only when created. */
export interface BulkStudentResult {
  name: string;
  email: string;
  status: "created" | "duplicate" | "invalid" | "error";
  temp_password: string | null;
  student_id: string | null;
  error: string | null;
}
export interface BulkImportResponse {
  results: BulkStudentResult[];
}

/** One filename → student match for the BP10 bulk-photo upload (decisions/0057). `matched`
 *  false = no student in this school (surfaced, never uploaded); `enrollment_status` lets the
 *  UI warn "already enrolled → will replace". */
export interface PhotoMatchResult {
  filename: string;
  matched: boolean;
  student_id: string | null;
  student_name: string | null;
  enrollment_status: EnrollmentStatus | null;
}
export interface MatchPhotosResponse {
  results: PhotoMatchResult[];
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

/** A short-lived direct-to-Supabase upload target (the token is inside `upload_url`). The FE
 *  PUTs the original and submits `object_path`; the backend generates the BP17 thumbnail. */
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
  // BP11b: a free-text term + the event's category (category_name denormalized for display).
  term: string | null;
  category_id: string | null;
  category_name: string | null;
}

/** A tenant-configurable event category (BP11b, decisions/0059). */
export interface EventCategoryResponse {
  id: string;
  name: string;
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
  // BP17: a backend-generated display thumbnail (null for video / pre-BP17 / a failed
  // generation). The FE requests ?size=thumb only when set, else the full-res object.
  thumbnail_path: string | null;
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
  failed: number; // BP8a: photos the ML worker couldn't process (retryable via redistribute)
  total: number;
}

/** A photo in a gallery — metadata only; fetch bytes via the download endpoint (0028). */
export interface GalleryMediaResponse {
  media_id: string;
  event_id: string;
  media_type: MediaType;
  // BP17: whether a display thumbnail exists — the tile requests ?size=thumb only when true
  // (null for video / pre-BP17 → the tile uses the full-res object).
  has_thumbnail: boolean;
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

/** One recorded media download — the school-admin trust audit (BP8b, decisions/0050).
 *  `actor_email` is null once the account is deleted; `actor_role` (denormalized) survives.
 *  `subject_student_*` is set only for a student's own self-download (null for staff). */
export interface DownloadAuditEntryResponse {
  id: string;
  media_id: string;
  event_id: string;
  event_name: string | null;
  actor_user_id: string | null;
  actor_email: string | null;
  actor_role: Role;
  subject_student_id: string | null;
  subject_student_name: string | null;
  downloaded_at: string;
}

/** One photo's download history — total count + the recent entries (newest first). */
export interface MediaDownloadLogResponse {
  count: number;
  entries: DownloadAuditEntryResponse[];
}

/** One page of the school-wide access log + the unpaginated total. */
export interface DownloadLogPageResponse {
  items: DownloadAuditEntryResponse[];
  total: number;
  limit: number;
  offset: number;
}

/** One page of any server-paginated list (BP9, decisions/0055): the page's rows + the
 *  unpaginated `total` for the current filter, plus the echoed `limit`/`offset`. */
export interface ListPage<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export type SortDir = "asc" | "desc";
/** Which rendition of an image to request (BP17): a small thumbnail for tiles/avatars, or
 *  the full-res original for the lightbox/download. */
export type PhotoSize = "thumb" | "full";
export type StudentListPageResponse = ListPage<StudentListItem>;
export type EventListPageResponse = ListPage<EventListItem>;
export type UserListPageResponse = ListPage<UserResponse>;
export type SchoolListPageResponse = ListPage<SchoolWithRollup>;
export type MediaListPageResponse = ListPage<MediaResponse>;

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
  /** First-run onboarding progress (BP7a, decisions/0044) — five booleans the dashboard
   *  renders as a guided checklist that retires once the school has distributed. */
  setup_checklist: {
    has_staff: boolean;
    has_enrolled_student: boolean;
    has_event: boolean;
    has_media: boolean;
    has_distributed: boolean;
  };
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
