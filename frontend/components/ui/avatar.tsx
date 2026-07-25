import { cn } from "@/lib/utils";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
}

/** A student avatar: the reference-photo thumbnail when available (BP17), else initials.
 *  A plain <img> (not next/image) — the signed Supabase object URL isn't in next.config's
 *  remotePatterns; the CSP already allows the Supabase host for img-src, and the image is
 *  pre-sized (a small stored thumbnail). */
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
        // eslint-disable-next-line @next/next/no-img-element
        <img src={photoUrl} alt="" width={36} height={36} className="size-full object-cover" />
      ) : (
        <span aria-hidden="true">{initials(name)}</span>
      )}
    </span>
  );
}
