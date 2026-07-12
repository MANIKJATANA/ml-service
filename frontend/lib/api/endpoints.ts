import { bffFetch } from "./client";
import type { LoginResult, SchoolResponse, UserResponse } from "./types";

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

/** Provision a school admin (temp password; must_change_password = true). */
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
