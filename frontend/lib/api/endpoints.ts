import { bffFetch } from "./client";
import type {
  BulkImportResponse,
  DashboardResponse,
  DownloadResponse,
  EventForStudentResponse,
  EventListItem,
  EventResponse,
  EventStatus,
  EventStatusResponse,
  GalleryMediaResponse,
  LoginResult,
  MediaAppearanceResponse,
  MediaResponse,
  MediaReviewResponse,
  MediaType,
  MyNotificationsResponse,
  NotificationRosterResponse,
  NotifyResultResponse,
  ProvisionedStudentResponse,
  ProvisionedUserResponse,
  SchoolResponse,
  SchoolWithRollup,
  StudentInEventResponse,
  StudentListItem,
  StudentResponse,
  UploadUrlResponse,
  UserResponse,
  UserStatus,
} from "./types";

/**
 * One typed function per BFF endpoint. Auth flows (login/logout/refresh/change-
 * password) are FE-owned cookie managers at `/api/auth/*`; everything else is a
 * transparent proxy to FastAPI under `/api/v1/*` (decisions/0031).
 */

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

export function listSchools(): Promise<SchoolWithRollup[]> {
  return bffFetch<SchoolWithRollup[]>("/api/v1/schools");
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

/** The school's administrator roster (BP2). */
export function listSchoolAdmins(schoolId: string): Promise<UserResponse[]> {
  return bffFetch<UserResponse[]>(`/api/v1/schools/${encodeURIComponent(schoolId)}/admins`);
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

export function listStaff(): Promise<UserResponse[]> {
  return bffFetch<UserResponse[]>("/api/v1/staff");
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

export function listStudents(): Promise<StudentListItem[]> {
  return bffFetch<StudentListItem[]>("/api/v1/students");
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

/** Retry ML enrollment using the stored reference photo (502 if ML is down). */
export function enrollStudent(studentId: string): Promise<StudentResponse> {
  return bffFetch<StudentResponse>(`/api/v1/students/${encodeURIComponent(studentId)}/enroll`, {
    method: "POST",
  });
}

export function deleteStudent(studentId: string): Promise<void> {
  return bffFetch<void>(`/api/v1/students/${encodeURIComponent(studentId)}`, {
    method: "DELETE",
  });
}

// --- Events (F4, event:manage / media:upload / job:status:view) ---

export function listEvents(): Promise<EventListItem[]> {
  return bffFetch<EventListItem[]>("/api/v1/events");
}

export function getEvent(eventId: string): Promise<EventResponse> {
  return bffFetch<EventResponse>(`/api/v1/events/${encodeURIComponent(eventId)}`);
}

export function createEvent(
  name: string,
  description: string | null,
  eventDate: string | null,
): Promise<EventResponse> {
  return bffFetch<EventResponse>("/api/v1/events", {
    method: "POST",
    body: JSON.stringify({ name, description, event_date: eventDate }),
  });
}

/** Partial update — only supplied fields change; clearing a field to null is unsupported (0027). */
export function updateEvent(
  eventId: string,
  patch: {
    name?: string;
    description?: string;
    event_date?: string;
    status?: EventStatus;
    auto_notify?: boolean;
  },
): Promise<EventResponse> {
  return bffFetch<EventResponse>(`/api/v1/events/${encodeURIComponent(eventId)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
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

/** Register an already-uploaded object as a media row (records only; no enqueue). */
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

export function listEventMedia(eventId: string): Promise<MediaResponse[]> {
  return bffFetch<MediaResponse[]>(`/api/v1/events/${encodeURIComponent(eventId)}/media`);
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

/** A student's "this isn't me" on their own photo — removes it from their gallery. */
export function reportNotMe(mediaId: string): Promise<void> {
  return bffFetch<void>(`/api/v1/me/media/${encodeURIComponent(mediaId)}/not-me`, {
    method: "POST",
  });
}

/** Mint a short-lived signed URL for one media's bytes (entitlement-gated: staff any
 *  in-school, a student only media they appear in, else 404). */
export function downloadMedia(mediaId: string): Promise<DownloadResponse> {
  return bffFetch<DownloadResponse>(`/api/v1/media/${encodeURIComponent(mediaId)}/download`);
}

// --- Student self-view (F6, gallery:view_own — the caller's own student_id from the token) ---

export function myEvents(): Promise<EventForStudentResponse[]> {
  return bffFetch<EventForStudentResponse[]>("/api/v1/me/events");
}

export function myMedia(eventId?: string): Promise<GalleryMediaResponse[]> {
  const query = eventId ? `?event_id=${encodeURIComponent(eventId)}` : "";
  return bffFetch<GalleryMediaResponse[]>(`/api/v1/me/media${query}`);
}
