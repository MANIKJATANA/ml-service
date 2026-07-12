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

/** A short-lived direct-to-Supabase upload target (the token is inside `upload_url`). */
export interface UploadUrlResponse {
  upload_url: string;
  object_path: string;
  max_upload_mb: number;
}

/** What the BFF login handler returns to the browser — never the tokens. */
export interface LoginResult {
  must_change_password: boolean;
}

/** The backend's uniform error body ({"detail": "..."}). */
export interface ApiErrorBody {
  detail: string;
}
