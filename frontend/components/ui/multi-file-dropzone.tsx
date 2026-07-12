"use client";

import { ImagePlus } from "lucide-react";
import { type DragEvent, useId, useState } from "react";

import { cn } from "@/lib/utils";

interface MultiFileDropzoneProps {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
  accept?: string;
  label?: string;
  hint?: string;
}

/** Drag-and-drop (or click) multi-file picker. Stateless: it just hands the chosen files
 *  up; the caller owns the upload queue + progress (decisions/0034). */
export function MultiFileDropzone({
  onFiles,
  disabled = false,
  accept = "image/*",
  label = "Photos",
  hint,
}: MultiFileDropzoneProps) {
  const inputId = useId();
  const [dragging, setDragging] = useState(false);

  function pick(files: FileList | null) {
    if (files && files.length > 0) onFiles(Array.from(files));
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    if (!disabled) pick(event.dataTransfer.files);
  }

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-body-sm font-medium text-ink">{label}</span>
      <label
        htmlFor={inputId}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-button border border-dashed px-4 py-10 text-center transition-colors focus-within:outline-none focus-within:ring-2 focus-within:ring-ring",
          dragging
            ? "border-accent bg-surface-2"
            : "border-hairline-strong bg-surface hover:bg-surface-2",
          disabled && "cursor-not-allowed opacity-50",
        )}
      >
        <ImagePlus className="size-6 text-ink-muted" aria-hidden="true" />
        <span className="text-body-sm text-ink-secondary">
          Drag photos here, or <span className="font-medium text-accent-hover">browse</span>
        </span>
        {hint ? <span className="text-body-sm text-ink-muted">{hint}</span> : null}
      </label>
      <input
        id={inputId}
        type="file"
        accept={accept}
        multiple
        disabled={disabled}
        className="sr-only"
        onChange={(e) => {
          pick(e.target.files);
          e.target.value = ""; // let the same files be picked again after a removal
        }}
      />
    </div>
  );
}
