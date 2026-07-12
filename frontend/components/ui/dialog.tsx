"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** Radix Dialog wrapper: scrim, centered panel, Esc/click-outside close, focus-trap
 *  and focus-return are handled by Radix. Always give a `title` (labels the dialog). */
export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

interface DialogContentProps {
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
}

export function DialogContent({ title, description, children, className }: DialogContentProps) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-ink/50" />
      <DialogPrimitive.Content
        className={cn(
          "fixed left-1/2 top-1/2 z-50 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-modal border border-hairline bg-canvas p-6 shadow-md focus:outline-none",
          className,
        )}
      >
        <div className="mb-5 flex items-start justify-between gap-4">
          <div className="flex flex-col gap-1">
            <DialogPrimitive.Title className="text-display-md text-ink">{title}</DialogPrimitive.Title>
            {description ? (
              <DialogPrimitive.Description className="text-body text-ink-secondary">
                {description}
              </DialogPrimitive.Description>
            ) : (
              // Radix requires a description for a11y; keep it off-screen when unused.
              <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>
            )}
          </div>
          <DialogPrimitive.Close
            aria-label="Close"
            className="-mr-1 -mt-1 rounded-button p-1 text-ink-muted transition-colors hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X className="size-5" />
          </DialogPrimitive.Close>
        </div>
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}
