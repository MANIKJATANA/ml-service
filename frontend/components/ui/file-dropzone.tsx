"use client";

import { ImagePlus, X } from "lucide-react";
import { type DragEvent, useEffect, useId, useMemo, useState } from "react";

import { cn } from "@/lib/utils";

interface FileDropzoneProps {
  file: File | null;
  onFileChange: (file: File | null) => void;
  disabled?: boolean;
  accept?: string;
  label?: string;
  hint?: string;
}

/** Drag-and-drop (or click) file picker with a thumbnail preview. Controlled: the
 *  parent owns the selected `file` and does the upload on submit (decisions/0033). */
export function FileDropzone({
  file,
  onFileChange,
  disabled = false,
  accept = "image/*",
  label = "Reference photo",
  hint,
}: FileDropzoneProps) {
  const inputId = useId();
  const [dragging, setDragging] = useState(false);
  // Object URL for the local preview; created via memo, revoked on change/unmount.
  const previewUrl = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);

  useEffect(() => {
    if (!previewUrl) return;
    return () => URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  function pick(files: FileList | null) {
    const next = files?.[0];
    if (next) onFileChange(next);
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    if (!disabled) pick(event.dataTransfer.files);
  }

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-body-sm font-medium text-ink">{label}</span>

      {file && previewUrl ? (
        <div className="flex items-center gap-3 rounded-button border border-hairline bg-surface p-3">
          {/* eslint-disable-next-line @next/next/no-img-element -- local blob preview */}
          <img
            src={previewUrl}
            alt="Selected reference photo"
            className="size-12 shrink-0 rounded-button object-cover"
          />
          <span className="min-w-0 flex-1 truncate text-body-sm text-ink" title={file.name}>
            {file.name}
          </span>
          <button
            type="button"
            onClick={() => onFileChange(null)}
            disabled={disabled}
            aria-label="Remove photo"
            className="rounded-button p-1 text-ink-muted transition-colors hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
          >
            <X className="size-4" />
          </button>
        </div>
      ) : (
        <label
          htmlFor={inputId}
          onDragOver={(e) => {
            e.preventDefault();
            if (!disabled) setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-button border border-dashed px-4 py-6 text-center transition-colors focus-within:outline-none focus-within:ring-2 focus-within:ring-ring",
            dragging ? "border-accent bg-surface-2" : "border-hairline-strong bg-surface hover:bg-surface-2",
            disabled && "cursor-not-allowed opacity-50",
          )}
        >
          <ImagePlus className="size-6 text-ink-muted" aria-hidden="true" />
          <span className="text-body-sm text-ink-secondary">
            Drag a photo here, or <span className="font-medium text-accent-hover">browse</span>
          </span>
          {hint ? <span className="text-body-sm text-ink-secondary">{hint}</span> : null}
        </label>
      )}

      <input
        id={inputId}
        type="file"
        accept={accept}
        disabled={disabled}
        className="sr-only"
        onChange={(e) => pick(e.target.files)}
      />
    </div>
  );
}
