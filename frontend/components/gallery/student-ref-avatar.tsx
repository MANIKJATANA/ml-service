"use client";

import { StudentAvatar } from "@/components/ui/avatar";
import { useStudentReferencePhoto } from "@/lib/hooks/use-student-reference-photo";

/**
 * A student's enrolled reference face for the staff review surfaces (BP22, R3-A3-02) — shown
 * next to a name so "is this the right person?" is a look, not a guess.
 *
 * The review/appearance payloads carry no photo-presence flag, so it fetches unconditionally;
 * SWR dedupes by the per-student key (the same face across many photos is one signed-URL mint)
 * and a photoless / 404 student falls back to initials (`shouldRetryOnError:false`). A match
 * candidate is an enrolled student, so it almost always resolves to a real face.
 *
 * The face is decorative (`alt=""` inside `StudentAvatar`): every call site renders the student's
 * name right beside it, so a labelled avatar would just double-announce. A future surface that
 * shows the face ALONE would need a real `alt`.
 */
export function StudentRefAvatar({
  studentId,
  name,
  className,
}: {
  studentId: string;
  name: string;
  className?: string;
}) {
  const { photoUrl } = useStudentReferencePhoto(studentId, true, "thumb");
  return <StudentAvatar name={name} photoUrl={photoUrl} className={className} />;
}
