import Image from "next/image";

import { cn } from "@/lib/utils";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
}

/** A student avatar: the reference-photo thumbnail when available, else initials.
 *  `photoUrl` is wired for when a reference-photo URL endpoint lands (decisions/0033). */
export function StudentAvatar({
  name,
  photoUrl,
  className,
}: {
  name: string;
  photoUrl?: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-full bg-surface-2 text-body-sm font-medium text-ink-secondary",
        className,
      )}
    >
      {photoUrl ? (
        <Image src={photoUrl} alt="" width={36} height={36} className="size-full object-cover" />
      ) : (
        <span aria-hidden="true">{initials(name)}</span>
      )}
    </span>
  );
}
