import { bffFetch } from "./client";
import type { LoginResult, SchoolResponse, StudentResponse, UploadUrlResponse, UserResponse } from "./types";

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
