import { bffFetch } from "./client";
import type {
  DashboardResponse,
  DownloadResponse,
  EventForStudentResponse,
  EventResponse,
  EventStatus,
  EventStatusResponse,
  GalleryMediaResponse,
  LoginResult,
  MediaAppearanceResponse,
  MediaResponse,
  MediaType,
  SchoolResponse,
  StudentInEventResponse,
  StudentResponse,
  UploadUrlResponse,
  UserResponse,
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

export function listSchools(): Promise<SchoolResponse[]> {
  return bffFetch<SchoolResponse[]>("/api/v1/schools");
}

export function createSchool(name: string, maxTeachers: number): Promise<SchoolResponse> {
  return bffFetch<SchoolResponse>("/api/v1/schools", {
    method: "POST",
    body: JSON.stringify({ name, max_teachers: maxTeachers }),
  });
}

export function getSchool(schoolId: string): Promise<SchoolResponse> {
  return bffFetch<SchoolResponse>(`/api/v1/schools/${encodeURIComponent(schoolId)}`);
}

export function createSchoolAdmin(
  schoolId: string,
  email: string,
  password: string,
): Promise<UserResponse> {
  return bffFetch<UserResponse>(`/api/v1/schools/${encodeURIComponent(schoolId)}/admins`, {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

// --- School staff / teachers (F3, staff:manage) ---

export function listStaff(): Promise<UserResponse[]> {
  return bffFetch<UserResponse[]>("/api/v1/staff");
}

export function createStaff(email: string, password: string): Promise<UserResponse> {
  return bffFetch<UserResponse>("/api/v1/staff", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

// --- Students + ML enrollment (F3, student:manage) ---

export function listStudents(): Promise<StudentResponse[]> {
  return bffFetch<StudentResponse[]>("/api/v1/students");
}

export function getStudent(studentId: string): Promise<StudentResponse> {
  return bffFetch<StudentResponse>(`/api/v1/students/${encodeURIComponent(studentId)}`);
}

/** Mint a signed target for the reference photo (bytes go browser→Supabase). */
export function studentUploadUrl(): Promise<UploadUrlResponse> {
  return bffFetch<UploadUrlResponse>("/api/v1/students/upload-url", { method: "POST" });
}

export function createStudent(
  name: string,
  email: string,
  password: string,
  referencePhotoPath: string,
): Promise<StudentResponse> {
  return bffFetch<StudentResponse>("/api/v1/students", {
    method: "POST",
    body: JSON.stringify({
      name,
      email,
      password,
      reference_photo_path: referencePhotoPath,
    }),
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

export function listEvents(): Promise<EventResponse[]> {
  return bffFetch<EventResponse[]>("/api/v1/events");
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
  patch: { name?: string; description?: string; event_date?: string; status?: EventStatus },
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
