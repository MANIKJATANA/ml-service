"use client";

import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

type ToastVariant = "success" | "error" | "info" | "warning";
/** BP20: `sticky` skips the auto-dismiss timer — the toast stays until the user closes it.
 *  Used for a partial/capped result the user needs to actually read (e.g. "saved the first 500"). */
interface ToastOptions {
  sticky?: boolean;
}
interface ToastItem {
  id: number;
  message: string;
  variant: ToastVariant;
}
interface ToastContextValue {
  toast: (message: string, variant?: ToastVariant, options?: ToastOptions) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within <ToastProvider>");
  return ctx;
}

const ICONS = { success: CheckCircle2, error: XCircle, info: Info, warning: AlertTriangle };
const ACCENTS = {
  success: "text-success",
  error: "text-error",
  info: "text-info",
  warning: "text-warning",
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextId = useRef(0);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const remove = useCallback((id: number) => {
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(
    (message: string, variant: ToastVariant = "info", options?: ToastOptions) => {
      const id = nextId.current++;
      setToasts((current) => [...current, { id, message, variant }]);
      // A sticky toast has no auto-dismiss timer — it waits for the user to close it (BP20).
      if (!options?.sticky) {
        timers.current.set(id, setTimeout(() => remove(id), 5000));
      }
    },
    [remove],
  );

  useEffect(() => {
    const pending = timers.current;
    return () => {
      pending.forEach(clearTimeout);
      pending.clear();
    };
  }, []);

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="false"
        className="pointer-events-none fixed inset-x-4 bottom-4 z-50 flex flex-col items-end gap-2 sm:inset-x-auto sm:right-4"
      >
        {toasts.map((t) => {
          const Icon = ICONS[t.variant];
          return (
            <div
              key={t.id}
              role={t.variant === "error" ? "alert" : "status"}
              className="pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-card border border-hairline bg-canvas p-3 shadow-md sm:min-w-[18rem]"
            >
              <Icon className={cn("mt-0.5 size-4 shrink-0", ACCENTS[t.variant])} aria-hidden="true" />
              <p className="flex-1 text-body-sm text-ink">{t.message}</p>
              <button
                type="button"
                onClick={() => remove(t.id)}
                aria-label="Dismiss notification"
                className="-m-1 rounded p-1 text-ink-muted transition-colors hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <X className="size-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
