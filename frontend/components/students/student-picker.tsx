"use client";

import * as Popover from "@radix-ui/react-popover";
import { useState } from "react";

import { buttonVariants } from "@/components/ui/button";
import { SearchInput } from "@/components/ui/search-input";
import type { EnrollmentStatus } from "@/lib/api/types";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { useStudents } from "@/lib/hooks/use-students";
import { cn } from "@/lib/utils";

export interface PickedStudent {
  id: string;
  name: string;
  email: string;
  enrollment_status: EnrollmentStatus;
}

/**
 * A single-select, type-to-search student picker (BP10, decisions/0057) — modelled on BP5's
 * "Add students" popover (`appearance-editor.tsx`), searching the existing server-paginated
 * students endpoint (`useStudents({ q })`) so the whole roster never loads. Used to change an
 * auto-matched row or assign a student to an unmatched photo. A student already assigned to
 * ANOTHER photo in the batch is shown disabled — no accidental double-assign.
 */
export function StudentPicker({
  triggerLabel,
  ariaLabel,
  disabledIds,
  onPick,
  container,
}: {
  triggerLabel: string;
  ariaLabel?: string;
  disabledIds: Set<string>;
  onPick: (student: PickedStudent) => void;
  // Portal target — pass the enclosing modal Dialog's content node so the list scrolls (a
  // body-portaled popover is blocked by the Dialog's scroll-lock). Defaults to <body>.
  container?: HTMLElement | null;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const debounced = useDebouncedValue(query.trim(), 250);
  const { items } = useStudents({ q: debounced || undefined });

  function choose(s: PickedStudent) {
    onPick(s);
    setOpen(false);
    setQuery("");
  }

  return (
    <Popover.Root
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) setQuery("");
      }}
    >
      <Popover.Trigger
        aria-label={ariaLabel}
        className={cn(buttonVariants({ variant: "secondary", size: "sm" }))}
      >
        {triggerLabel}
      </Popover.Trigger>
      <Popover.Portal container={container ?? undefined}>
        <Popover.Content
          align="end"
          sideOffset={6}
          collisionPadding={12}
          className="z-[60] flex w-72 flex-col gap-2 rounded-card border border-hairline bg-canvas p-3 shadow-lg focus-visible:outline-none"
        >
          <SearchInput
            value={query}
            onChange={setQuery}
            placeholder="Search students…"
            className="sm:max-w-none"
          />
          <ul className="max-h-56 overflow-y-auto overscroll-contain rounded-button border border-hairline">
            {items.length === 0 ? (
              <li className="px-2 py-2 text-body-sm text-ink-secondary">
                {debounced ? "No students found." : "Search to pick a student."}
              </li>
            ) : (
              items.map((s) => {
                const disabled = disabledIds.has(s.id);
                return (
                  <li key={s.id}>
                    <button
                      type="button"
                      disabled={disabled}
                      onClick={() =>
                        choose({
                          id: s.id,
                          name: s.name,
                          email: s.email,
                          enrollment_status: s.enrollment_status,
                        })
                      }
                      className="flex w-full items-center gap-2 px-2 py-1.5 text-left hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <span className="min-w-0 flex-1 truncate text-body-sm text-ink">
                        {s.name}
                      </span>
                      <span className="min-w-0 shrink truncate text-body-sm text-ink-secondary">
                        {s.email}
                      </span>
                      {disabled ? (
                        <span className="shrink-0 text-body-sm text-ink-secondary">assigned</span>
                      ) : null}
                    </button>
                  </li>
                );
              })
            )}
          </ul>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
