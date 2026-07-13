import type { ReactNode } from "react";

/**
 * Centered full-viewport message (error / 404 / can't-reach-server). One shared shell so the
 * surfaces stay identical, with a real <h1> for heading navigation. `global-error.tsx` is the
 * one exception — it renders above the root layout, so it can't use Tailwind (decisions/0037).
 */
export function FullPageMessage({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-surface px-4 text-center">
      <div className="flex flex-col gap-1">
        <h1 className="text-display-md text-ink">{title}</h1>
        {description ? <p className="text-body text-ink-secondary">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}
