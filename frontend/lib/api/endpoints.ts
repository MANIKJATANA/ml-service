import { bffFetch } from "./client";
import type {
  BulkImportResponse,
  ClassListResponse,
  ClassRefListResponse,
  ClassResponse,
  DashboardResponse,
  DownloadLogPageResponse,
  DownloadResponse,
  EventCategoryResponse,
  EventForStudentResponse,
  EventListPageResponse,
  EventResponse,
  EventStatus,
  EventStatusResponse,
  GalleryMediaResponse,
  LoginResult,
  MatchPhotosResponse,
  MediaAppearanceResponse,
  MediaDownloadLogResponse,
  MediaListPageResponse,
  MediaResponse,
  MediaReviewResponse,
  MediaType,
  MyNotificationsResponse,
  NotificationRosterResponse,
  NotifyResultResponse,
  PhotoSize,
  ProvisionedStudentResponse,
  ProvisionedUserResponse,
  SchoolListPageResponse,
  SchoolResponse,
  SchoolWithRollup,
  SortDir,
  StudentInEventResponse,
  StudentListPageResponse,
  StudentResponse,
  UploadUrlResponse,
  UserListPageResponse,
  UserResponse,
  UserStatus,
} from "./types";

/**
 * One typed function per BFF endpoint. Auth flows (login/logout/refresh/change-
 * password) are FE-owned cookie managers at `/api/auth/*`; everything else is a
 * transparent proxy to FastAPI under `/api/v1/*` (decisions/0031).
 */

/** Shared query params for the server-paginated lists (BP9, decisions/0055). */
export interface ListParams {
  limit: number;
  offset: number;
  q?: string;
  sort?: string;
  dir?: SortDir;
  status?: string;
  student_group_id?: string; // BP11a/BP11c: filter students/events list to one class
  category_id?: string; // BP11b: filter the events list to one category
  term?: string; // BP11b: filter the events list to one term
  date_from?: string; // BP11b: event_date >= (the calendar month window)
  date_to?: string; // BP11b: event_date <=
  mine?: boolean; // BP11c: a teacher's "focus" — scope the list to their assigned classes
}

function listQuery(params: ListParams): string {
  const q = new URLSearchParams({
    limit: String(params.limit),
    offset: String(params.offset),
  });
  if (params.q) q.set("q", params.q);
  if (params.sort) q.set("sort", params.sort);
  if (params.dir) q.set("dir", params.dir);
  if (params.status && params.status !== "all") q.set("status", params.status);
  if (params.student_group_id) q.set("student_group_id", params.student_group_id);
  if (params.category_id) q.set("category_id", params.category_id);
  if (params.term) q.set("term", params.term);
  if (params.date_from) q.set("date_from", params.date_from);
  if (params.date_to) q.set("date_to", params.date_to);
  if (params.mine) q.set("mine", "true");
  return q.toString();
}

// --- Auth (F1) ---

export function login(email: string, password: string): Promise<LoginResult> {
  return bffFetch<LoginResult>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function logout(): Promise<void> {
  return bffFetch<void>("/api/auth/logout", { method: "POST" });
}

export function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  return bffFetch<void>("/api/auth/change-password", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
}

/** Current authenticated user (proxied to GET /v1/auth/me, with refresh-retry). */
export function getMe(): Promise<UserResponse> {
  return bffFetch<UserResponse>("/api/v1/auth/me");
}

// --- Dashboard (BP1, dashboard:view — school_admin + teacher) ---

/** The caller's school command-center rollup (tenant is the token's school). */
export function getDashboard(): Promise<DashboardResponse> {
  return bffFetch<DashboardResponse>("/api/v1/dashboard");
}

// --- Platform: schools + admins (F2, school:manage) ---

/** One page of the platform schools list (BP9): server search + rollup-count sort. */
export function getSchools(params: ListParams): Promise<SchoolListPageResponse> {
  return bffFetch<SchoolListPageResponse>(`/api/v1/schools?${listQuery(params)}`);
}

export function createSchool(name: string, maxTeachers: number): Promise<SchoolResponse> {
  return bffFetch<SchoolResponse>("/api/v1/schools", {
    method: "POST",
    body: JSON.stringify({ name, max_teachers: maxTeachers }),
  });
}

export function getSchool(schoolId: string): Promise<SchoolWithRollup> {
  return bffFetch<SchoolWithRollup>(`/api/v1/schools/${encodeURIComponent(schoolId)}`);
}

/** One page of the school's administrator roster (BP9): server search + email/created sort. */
export function getSchoolAdmins(
  schoolId: string,
  params: ListParams,
): Promise<UserListPageResponse> {
  return bffFetch<UserListPageResponse>(
    `/api/v1/schools/${encodeURIComponent(schoolId)}/admins?${listQuery(params)}`,
  );
}

/** Add a school admin (BP7c): the temp password is generated server-side + returned once. */
export function createSchoolAdmin(
  schoolId: string,
  email: string,
): Promise<ProvisionedUserResponse> {
  return bffFetch<ProvisionedUserResponse>(
    `/api/v1/schools/${encodeURIComponent(schoolId)}/admins`,
    { method: "POST", body: JSON.stringify({ email }) },
  );
}

/** Enable/disable a school admin (BP7c). */
export function setSchoolAdminStatus(
  schoolId: string,
  userId: string,
  status: UserStatus,
): Promise<UserResponse> {
  return bffFetch<UserResponse>(
    `/api/v1/schools/${encodeURIComponent(schoolId)}/admins/${encodeURIComponent(userId)}`,
    { method: "PATCH", body: JSON.stringify({ status }) },
  );
}

/** Re-issue a one-time temp password for a school admin (BP7c). */
export function resendSchoolAdminInvite(
  schoolId: string,
  userId: string,
): Promise<ProvisionedUserResponse> {
  return bffFetch<ProvisionedUserResponse>(
    `/api/v1/schools/${encodeURIComponent(schoolId)}/admins/${encodeURIComponent(userId)}/resend-invite`,
    { method: "POST" },
  );
}

// --- School staff / teachers (F3, staff:manage) ---

/** One page of the teacher roster (BP9): server search (email) + email/created sort. */
export function getStaff(params: ListParams): Promise<UserListPageResponse> {
  return bffFetch<UserListPageResponse>(`/api/v1/staff?${listQuery(params)}`);
}

/** Add a teacher (BP7c): the temp password is generated server-side + returned once. */
export function createStaff(email: string): Promise<ProvisionedUserResponse> {
  return bffFetch<ProvisionedUserResponse>("/api/v1/staff", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

/** Enable/disable a teacher (BP7c). */
export function setStaffStatus(
  userId: string,
  status: UserStatus,
): Promise<UserResponse> {
  return bffFetch<UserResponse>(`/api/v1/staff/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

/** Re-issue a one-time temp password for a teacher (BP7c). */
export function resendStaffInvite(userId: string): Promise<ProvisionedUserResponse> {
  return bffFetch<ProvisionedUserResponse>(
    `/api/v1/staff/${encodeURIComponent(userId)}/resend-invite`,
    { method: "POST" },
  );
}

// --- Students + ML enrollment (F3, student:manage) ---

/** One page of the students list (BP9): server search (name/email), sort (incl. the
 *  whole-list appearance/event count columns), and enrollment-status filter. */
export function getStudents(params: ListParams): Promise<StudentListPageResponse> {
  return bffFetch<StudentListPageResponse>(`/api/v1/students?${listQuery(params)}`);
}

export function getStudent(studentId: string): Promise<StudentResponse> {
  return bffFetch<StudentResponse>(`/api/v1/students/${encodeURIComponent(studentId)}`);
}

/** Mint a signed target for the reference photo (bytes go browser→Supabase). */
export function studentUploadUrl(): Promise<UploadUrlResponse> {
  return bffFetch<UploadUrlResponse>("/api/v1/students/upload-url", { method: "POST" });
}

/** Create a student (BP7d): the temp password is server-generated + returned once; the
 *  reference photo is optional (omit -> a photoless, pending student). */
export function createStudent(
  name: string,
  email: string,
  referencePhotoPath: string | null,
): Promise<ProvisionedStudentResponse> {
  return bffFetch<ProvisionedStudentResponse>("/api/v1/students", {
    method: "POST",
    body: JSON.stringify({
      name,
      email,
      reference_photo_path: referencePhotoPath,
    }),
  });
}

/** Bulk-create students from CSV rows (BP7d) — best-effort, photoless (pending). */
export function bulkImportStudents(
  rows: { name: string; email: string }[],
): Promise<BulkImportResponse> {
  return bffFetch<BulkImportResponse>("/api/v1/students/bulk", {
    method: "POST",
    body: JSON.stringify({ students: rows }),
  });
}

/** Map photo filenames to students for bulk enrollment (BP10) — auto-fills the mapping table;
 *  tenant from the token, the batch size capped server-side (422 over the cap). */
export function matchPhotos(filenames: string[]): Promise<MatchPhotosResponse> {
  return bffFetch<MatchPhotosResponse>("/api/v1/students/match-photos", {
    method: "POST",
    body: JSON.stringify({ filenames }),
  });
}

/** Best-effort cleanup of an orphaned bulk-photo upload (BP10) — an object uploaded but never
 *  attached to a student. Guarded to the caller's own tenant prefix server-side; idempotent. */
export function deleteReferencePhotoUpload(objectPath: string): Promise<void> {
  return bffFetch<void>(
    `/api/v1/students/reference-photo-upload?path=${encodeURIComponent(objectPath)}`,
    { method: "DELETE" },
  );
}

/** Retry ML enrollment using the stored reference photo (502 if ML is down). */
export function enrollStudent(studentId: string): Promise<StudentResponse> {
  return bffFetch<StudentResponse>(`/api/v1/students/${encodeURIComponent(studentId)}/enroll`, {
    method: "POST",
  });
}

/** Set/replace a student's reference photo, then re-enroll (BP7d-2). */
export function setStudentReferencePhoto(
  studentId: string,
  referencePhotoPath: string,
): Promise<StudentResponse> {
  return bffFetch<StudentResponse>(
    `/api/v1/students/${encodeURIComponent(studentId)}/reference-photo`,
    {
      method: "PUT",
      body: JSON.stringify({ reference_photo_path: referencePhotoPath }),
    },
  );
}

export function deleteStudent(studentId: string): Promise<void> {
  return bffFetch<void>(`/api/v1/students/${encodeURIComponent(studentId)}`, {
    method: "DELETE",
  });
}

// --- Classes (BP11a, decisions/0058) ---

/** Every class in the school + its member count (student:manage reads; feeds the filter). */
export function getClasses(): Promise<ClassListResponse> {
  return bffFetch<ClassListResponse>("/api/v1/classes");
}

/** Create a class (class:manage — school_admin only). */
export function createClass(
  name: string,
  grade: string | null,
  section: string | null,
): Promise<ClassResponse> {
  return bffFetch<ClassResponse>("/api/v1/classes", {
    method: "POST",
    body: JSON.stringify({ name, grade, section }),
  });
}

/** Rename/edit a class (class:manage). Full replace — omitting `grade`/`section` clears them. */
export function updateClass(
  classId: string,
  patch: { name: string; grade: string | null; section: string | null },
): Promise<ClassResponse> {
  return bffFetch<ClassResponse>(`/api/v1/classes/${encodeURIComponent(classId)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

/** Delete a class — its students are un-assigned (SET NULL), never deleted (class:manage). */
export function deleteClass(classId: string): Promise<void> {
  return bffFetch<void>(`/api/v1/classes/${encodeURIComponent(classId)}`, {
    method: "DELETE",
  });
}

/** Bulk-add students to a class (student:manage). Returns how many were assigned. */
export function assignStudentsToClass(
  classId: string,
  studentIds: string[],
): Promise<{ assigned: number }> {
  return bffFetch<{ assigned: number }>(
    `/api/v1/classes/${encodeURIComponent(classId)}/members`,
    { method: "POST", body: JSON.stringify({ student_ids: studentIds }) },
  );
}

/** Set (or clear, with `null`) one student's class (student:manage). */
export function setStudentClass(
  studentId: string,
  classId: string | null,
): Promise<StudentResponse> {
  return bffFetch<StudentResponse>(`/api/v1/students/${encodeURIComponent(studentId)}`, {
    method: "PATCH",
    body: JSON.stringify({ student_group_id: classId }),
  });
}

// --- Teacher delegation (BP11c, decisions/0060) ---

/** The caller-teacher's own assigned classes (student:manage) — labels their list "focus". */
export function getMyClasses(): Promise<ClassRefListResponse> {
  return bffFetch<ClassRefListResponse>("/api/v1/classes/mine");
}

/** The teachers assigned to a class (class:manage — school_admin only). */
export function getClassTeachers(classId: string): Promise<UserResponse[]> {
  return bffFetch<UserResponse[]>(
    `/api/v1/classes/${encodeURIComponent(classId)}/teachers`,
  );
}

/** Bulk-assign teachers to a class (class:manage). Returns how many were linked. */
export function assignTeachersToClass(
  classId: string,
  teacherIds: string[],
): Promise<{ assigned: number }> {
  return bffFetch<{ assigned: number }>(
    `/api/v1/classes/${encodeURIComponent(classId)}/teachers`,
    { method: "POST", body: JSON.stringify({ teacher_ids: teacherIds }) },
  );
}

/** Unassign one teacher from a class (class:manage). */
export function removeClassTeacher(classId: string, teacherId: string): Promise<void> {
  return bffFetch<void>(
    `/api/v1/classes/${encodeURIComponent(classId)}/teachers/${encodeURIComponent(teacherId)}`,
    { method: "DELETE" },
  );
}

/** The classes one teacher is assigned to (class:manage) — the staff-row chip. */
export function getTeacherClasses(userId: string): Promise<ClassRefListResponse> {
  return bffFetch<ClassRefListResponse>(
    `/api/v1/staff/${encodeURIComponent(userId)}/classes`,
  );
}

/** Replace a teacher's whole class set (class:manage) — the "Edit classes" dialog. */
export function setTeacherClasses(
  userId: string,
  groupIds: string[],
): Promise<ClassRefListResponse> {
  return bffFetch<ClassRefListResponse>(
    `/api/v1/staff/${encodeURIComponent(userId)}/classes`,
    { method: "PUT", body: JSON.stringify({ group_ids: groupIds }) },
  );
}

// --- Events (F4, event:manage / media:upload / job:status:view) ---

/** One page of the events list (BP9): server search (name), sort (incl. the whole-list
 *  media/matched/needs-review count columns), and lifecycle-status filter. */
export function getEvents(params: ListParams): Promise<EventListPageResponse> {
  return bffFetch<EventListPageResponse>(`/api/v1/events?${listQuery(params)}`);
}

export function getEvent(eventId: string): Promise<EventResponse> {
  return bffFetch<EventResponse>(`/api/v1/events/${encodeURIComponent(eventId)}`);
}

export function createEvent(
  name: string,
  description: string | null,
  eventDate: string | null,
  categoryId: string | null = null,
  term: string | null = null,
  studentGroupId: string | null = null,
): Promise<EventResponse> {
  return bffFetch<EventResponse>("/api/v1/events", {
    method: "POST",
    body: JSON.stringify({
      name,
      description,
      event_date: eventDate,
      category_id: categoryId,
      term,
      student_group_id: studentGroupId,
    }),
  });
}

/** Partial update — only supplied fields change; clearing a field to null is unsupported (0027).
 *  BP11b/BP11c: `category_id`/`term`/`student_group_id` follow the same convention (send to set,
 *  omit to leave unchanged). */
export function updateEvent(
  eventId: string,
  patch: {
    name?: string;
    description?: string;
    event_date?: string;
    status?: EventStatus;
    auto_notify?: boolean;
    category_id?: string;
    term?: string;
    student_group_id?: string;
  },
): Promise<EventResponse> {
  return bffFetch<EventResponse>(`/api/v1/events/${encodeURIComponent(eventId)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

/** Archive/restore many events at once (BP13). Tenant from the token; a foreign id is silently
 *  skipped. Returns how many were updated. */
export function bulkEventStatus(
  eventIds: string[],
  status: EventStatus,
): Promise<{ updated: number }> {
  return bffFetch<{ updated: number }>("/api/v1/events/bulk-status", {
    method: "POST",
    body: JSON.stringify({ event_ids: eventIds, status }),
  });
}

// --- Event categories + terms (BP11b, decisions/0059; event:manage) ---

/** Every category in the school (bounded — feeds the filter + the create/edit picker). */
export function getEventCategories(): Promise<EventCategoryResponse[]> {
  return bffFetch<EventCategoryResponse[]>("/api/v1/event-categories");
}

/** Add a category (a duplicate name in the school → 409). */
export function createEventCategory(name: string): Promise<EventCategoryResponse> {
  return bffFetch<EventCategoryResponse>("/api/v1/event-categories", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

/** Remove a category — its events are un-tagged (SET NULL), never deleted. */
export function deleteEventCategory(categoryId: string): Promise<void> {
  return bffFetch<void>(`/api/v1/event-categories/${encodeURIComponent(categoryId)}`, {
    method: "DELETE",
  });
}

/** The distinct terms this school has used (feeds the term filter dropdown). */
export function getEventTerms(): Promise<{ terms: string[] }> {
  return bffFetch<{ terms: string[] }>("/api/v1/events/terms");
}

/** Enqueue one event-level inference job. 400 if archived / already in flight / no pending
 *  photos; 502 if the queue (Redis) is down. */
export function processEvent(eventId: string): Promise<EventResponse> {
  return bffFetch<EventResponse>(`/api/v1/events/${encodeURIComponent(eventId)}/process`, {
    method: "POST",
  });
}

export function getEventStatus(eventId: string): Promise<EventStatusResponse> {
  return bffFetch<EventStatusResponse>(
    `/api/v1/events/${encodeURIComponent(eventId)}/status`,
  );
}

// --- Notifications / distribution (BP4, decisions/0041) ---

/** Announce a completed event's photos to the students in them + fan out to channels. */
export function notifyStudents(eventId: string): Promise<NotifyResultResponse> {
  return bffFetch<NotifyResultResponse>(
    `/api/v1/events/${encodeURIComponent(eventId)}/notify`,
    { method: "POST" },
  );
}

/** The staff "notified / seen" roster for an event. */
export function eventNotifications(eventId: string): Promise<NotificationRosterResponse> {
  return bffFetch<NotificationRosterResponse>(
    `/api/v1/events/${encodeURIComponent(eventId)}/notifications`,
  );
}

/** The logged-in student's "new photos" signal (unseen tally + announced events). */
export function myNotifications(): Promise<MyNotificationsResponse> {
  return bffFetch<MyNotificationsResponse>("/api/v1/me/notifications");
}

/** Mark one event's photos seen (clears it from the student's new-photos signal). */
export function markNotificationSeen(eventId: string): Promise<void> {
  return bffFetch<void>(
    `/api/v1/me/notifications/${encodeURIComponent(eventId)}/seen`,
    { method: "POST" },
  );
}

// --- Event media (F4) ---

/** Mint a signed target for one event photo (bytes go browser→Supabase). */
export function eventMediaUploadUrl(eventId: string): Promise<UploadUrlResponse> {
  return bffFetch<UploadUrlResponse>(
    `/api/v1/events/${encodeURIComponent(eventId)}/media/upload-url`,
    { method: "POST" },
  );
}

/** Register an already-uploaded object as a media row (records only; no enqueue). BP17: for
 *  an image the backend generates the display thumbnail from `storagePath` on register. */
export function registerMedia(
  eventId: string,
  storagePath: string,
  mediaType: MediaType,
): Promise<MediaResponse> {
  return bffFetch<MediaResponse>(`/api/v1/events/${encodeURIComponent(eventId)}/media`, {
    method: "POST",
    body: JSON.stringify({ storage_path: storagePath, media_type: mediaType }),
  });
}

/** One page of an event's media (BP9): pagination for the browse-all gallery + detail. */
export function getEventMedia(
  eventId: string,
  params: ListParams,
): Promise<MediaListPageResponse> {
  return bffFetch<MediaListPageResponse>(
    `/api/v1/events/${encodeURIComponent(eventId)}/media?${listQuery(params)}`,
  );
}

export function getMedia(mediaId: string): Promise<MediaResponse> {
  return bffFetch<MediaResponse>(`/api/v1/media/${encodeURIComponent(mediaId)}`);
}

// --- Galleries + download (F5, gallery:view_all; download is entitlement-scoped) ---

export function eventStudents(eventId: string): Promise<StudentInEventResponse[]> {
  return bffFetch<StudentInEventResponse[]>(
    `/api/v1/events/${encodeURIComponent(eventId)}/students`,
  );
}

export function eventStudentMedia(
  eventId: string,
  studentId: string,
): Promise<GalleryMediaResponse[]> {
  return bffFetch<GalleryMediaResponse[]>(
    `/api/v1/events/${encodeURIComponent(eventId)}/students/${encodeURIComponent(studentId)}/media`,
  );
}

export function studentEvents(studentId: string): Promise<EventForStudentResponse[]> {
  return bffFetch<EventForStudentResponse[]>(
    `/api/v1/students/${encodeURIComponent(studentId)}/events`,
  );
}

export function studentMedia(
  studentId: string,
  eventId?: string,
): Promise<GalleryMediaResponse[]> {
  const query = eventId ? `?event_id=${encodeURIComponent(eventId)}` : "";
  return bffFetch<GalleryMediaResponse[]>(
    `/api/v1/students/${encodeURIComponent(studentId)}/media${query}`,
  );
}

export function mediaAppearances(mediaId: string): Promise<MediaAppearanceResponse[]> {
  return bffFetch<MediaAppearanceResponse[]>(
    `/api/v1/media/${encodeURIComponent(mediaId)}/appearances`,
  );
}

// --- Match review / trust & accuracy (BP5, match:review) ---

/** Confirm or reject a match. Rejecting hides the photo from the student. */
export function setMatchVerdict(
  mediaId: string,
  studentId: string,
  verdict: "confirmed" | "rejected",
): Promise<void> {
  return bffFetch<void>(
    `/api/v1/media/${encodeURIComponent(mediaId)}/appearances/${encodeURIComponent(studentId)}`,
    { method: "POST", body: JSON.stringify({ verdict }) },
  );
}

/** Report-a-miss: add a student the ML missed to this photo. */
export function addMissedStudent(mediaId: string, studentId: string): Promise<void> {
  return bffFetch<void>(`/api/v1/media/${encodeURIComponent(mediaId)}/appearances`, {
    method: "POST",
    body: JSON.stringify({ student_id: studentId }),
  });
}

/** Undo a correction — reverts to the raw ML truth. */
export function undoCorrection(mediaId: string, studentId: string): Promise<void> {
  return bffFetch<void>(
    `/api/v1/media/${encodeURIComponent(mediaId)}/appearances/${encodeURIComponent(studentId)}`,
    { method: "DELETE" },
  );
}

/** The event's unresolved ambiguous matches grouped by photo (the review lane). */
export function eventReview(eventId: string): Promise<MediaReviewResponse[]> {
  return bffFetch<MediaReviewResponse[]>(
    `/api/v1/events/${encodeURIComponent(eventId)}/review`,
  );
}

/** Apply many confirm/reject verdicts over an event's review lane at once (BP13). A pair that
 *  isn't a real match in the event is silently skipped server-side. Returns how many applied. */
export function batchReview(
  eventId: string,
  verdicts: { media_id: string; student_id: string; verdict: "confirmed" | "rejected" }[],
): Promise<{ applied: number }> {
  return bffFetch<{ applied: number }>(
    `/api/v1/events/${encodeURIComponent(eventId)}/review/batch`,
    { method: "POST", body: JSON.stringify({ verdicts }) },
  );
}

/** A student's "this isn't me" on their own photo — removes it from their gallery. */
export function reportNotMe(mediaId: string): Promise<void> {
  return bffFetch<void>(`/api/v1/me/media/${encodeURIComponent(mediaId)}/not-me`, {
    method: "POST",
  });
}

/** Mint a short-lived signed URL for one media's bytes (entitlement-gated: staff any
 *  in-school, a student only media they appear in, else 404). Used for BOTH viewing and
 *  downloading, so it records nothing — `recordDownload` audits the actual download. */
export function downloadMedia(
  mediaId: string,
  size: PhotoSize = "full",
): Promise<DownloadResponse> {
  // BP17: `thumb` asks for a downscaled image (tiles/avatars); `full` (default) is the
  // original used by the lightbox + the download save.
  const q = size === "thumb" ? "?size=thumb" : "";
  return bffFetch<DownloadResponse>(
    `/api/v1/media/${encodeURIComponent(mediaId)}/download${q}`,
  );
}

/** A signed URL for a student's reference photo — the staff avatar (BP17). Thumbnail by
 *  default; 404 if the student is photoless. */
export function studentReferencePhoto(
  studentId: string,
  size: PhotoSize = "thumb",
): Promise<DownloadResponse> {
  const q = size === "full" ? "?size=full" : "";
  return bffFetch<DownloadResponse>(
    `/api/v1/students/${encodeURIComponent(studentId)}/reference-photo${q}`,
  );
}

/** Record one actual media download in the audit (BP8b) — fired only when the user saves a
 *  media, never on a mere view. Same entitlement gate as the mint (404 if not entitled). */
export function recordDownload(mediaId: string): Promise<void> {
  return bffFetch<void>(`/api/v1/media/${encodeURIComponent(mediaId)}/download`, {
    method: "POST",
  });
}

// --- Access / download audit (BP8b, audit:view — school_admin only) ---

/** One photo's download history (who downloaded it + when). School-admin only (403 else). */
export function getMediaDownloadLog(mediaId: string): Promise<MediaDownloadLogResponse> {
  return bffFetch<MediaDownloadLogResponse>(
    `/api/v1/media/${encodeURIComponent(mediaId)}/download-log`,
  );
}

/** One page of the school-wide access log, newest first (school-admin only). */
export function getDownloadLog(params: {
  limit: number;
  offset: number;
  eventId?: string;
  studentId?: string;
}): Promise<DownloadLogPageResponse> {
  const q = new URLSearchParams({
    limit: String(params.limit),
    offset: String(params.offset),
  });
  if (params.eventId) q.set("event_id", params.eventId);
  if (params.studentId) q.set("student_id", params.studentId);
  return bffFetch<DownloadLogPageResponse>(`/api/v1/audit/downloads?${q.toString()}`);
}

// --- Student self-view (F6, gallery:view_own — the caller's own student_id from the token) ---

export function myEvents(): Promise<EventForStudentResponse[]> {
  return bffFetch<EventForStudentResponse[]>("/api/v1/me/events");
}

export function myMedia(eventId?: string): Promise<GalleryMediaResponse[]> {
  const query = eventId ? `?event_id=${encodeURIComponent(eventId)}` : "";
  return bffFetch<GalleryMediaResponse[]>(`/api/v1/me/media${query}`);
}
