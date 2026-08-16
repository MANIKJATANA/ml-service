import { cloneElement, isValidElement, type ReactNode } from "react";

import { cn } from "@/lib/utils";

interface FieldProps {
  label: string;
  htmlFor: string;
  error?: string;
  hint?: string;
  children: ReactNode;
  className?: string;
}

/**
 * Label + control + hint/error. Wires the hint/error text to the control via
 * `aria-describedby` (cloned onto the child) so screen readers announce it.
 */
export function Field({ label, htmlFor, error, hint, children, className }: FieldProps) {
  const describedById = error ? `${htmlFor}-error` : hint ? `${htmlFor}-hint` : undefined;

  const control =
    describedById && isValidElement<{ "aria-describedby"?: string }>(children)
      ? cloneElement(children, {
          "aria-describedby":
            [children.props["aria-describedby"], describedById].filter(Boolean).join(" ") ||
            undefined,
        })
      : children;

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={htmlFor} className="text-body-sm font-medium text-ink">
        {label}
      </label>
      {control}
      {error ? (
        <p id={`${htmlFor}-error`} className="text-body-sm text-error-strong">
          {error}
        </p>
      ) : hint ? (
        <p id={`${htmlFor}-hint`} className="text-body-sm text-ink-secondary">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
