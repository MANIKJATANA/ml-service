"use client";

import { Tags, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogClose, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { createEventCategory, deleteEventCategory } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import { categoryColor } from "@/lib/events/categories";
import { useEventCategories } from "@/lib/hooks/use-event-categories";
import { cn } from "@/lib/utils";

/**
 * Manage the school's event categories (BP11b, decisions/0059) — list / add / remove. Rendered
 * inline in a modal dialog (not a portaled popover), so its list scrolls under the scroll-lock.
 * On `event:manage` (admins + staff). `onChanged` lets the events page refresh filters/rows.
 */
export function ManageCategoriesDialog({ onChanged }: { onChanged?: () => void }) {
  const { toast } = useToast();
  const { categories, isLoading, mutate } = useEventCategories();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [adding, setAdding] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<{ id: string; name: string } | null>(null);

  function refresh() {
    void mutate();
    onChanged?.();
  }

  async function onAdd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const clean = name.trim();
    if (!clean) return;
    setAdding(true);
    try {
      await createEventCategory(clean);
      setName("");
      refresh();
      toast("Category added.", "success");
    } catch (err) {
      // 409 = a category with that name already exists in the school.
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setAdding(false);
    }
  }

  async function onDelete(id: string, label: string) {
    setBusyId(id);
    try {
      await deleteEventCategory(id);
      refresh();
      toast(`Removed "${label}".`, "success");
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setBusyId(null);
      setConfirming(null);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setName("");
      }}
    >
      <DialogTrigger asChild>
        <Button variant="secondary">
          <Tags className="size-4" aria-hidden="true" />
          Categories
        </Button>
      </DialogTrigger>
      <DialogContent
        title="Manage categories"
        description="Add or remove event categories. Removing one un-tags its events — it never deletes events."
      >
        <div className="flex flex-col gap-3">
          <ul
            className="max-h-64 divide-y divide-hairline overflow-y-auto overscroll-contain rounded-button border border-hairline"
            aria-label="Categories"
          >
            {isLoading ? (
              <li className="px-3 py-3 text-body-sm text-ink-muted">Loading…</li>
            ) : categories.length === 0 ? (
              <li className="px-3 py-3 text-body-sm text-ink-muted">No categories yet.</li>
            ) : (
              categories.map((c) => (
                <li key={c.id} className="flex items-center gap-2 px-3 py-2">
                  <span
                    className={cn(
                      "rounded-full px-2.5 py-0.5 text-body-sm font-medium",
                      categoryColor(c.id),
                    )}
                  >
                    {c.name}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="ml-auto"
                    aria-label={`Remove ${c.name}`}
                    loading={busyId === c.id}
                    onClick={() => setConfirming({ id: c.id, name: c.name })}
                  >
                    <Trash2 className="size-4 text-error" aria-hidden="true" />
                  </Button>
                </li>
              ))
            )}
          </ul>
          <form onSubmit={onAdd} className="flex gap-2">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="New category name…"
              maxLength={60}
              aria-label="New category name"
            />
            <Button type="submit" loading={adding} disabled={!name.trim()}>
              Add
            </Button>
          </form>
          <div className="mt-1 flex justify-end">
            <DialogClose asChild>
              <Button type="button" variant="secondary">
                Done
              </Button>
            </DialogClose>
          </div>
        </div>
      </DialogContent>
      <ConfirmDialog
        open={confirming !== null}
        onOpenChange={(next) => {
          if (!next) setConfirming(null);
        }}
        title={confirming ? `Remove “${confirming.name}”?` : ""}
        description="Events tagged with this category become uncategorized. This can't be undone."
        confirmLabel="Remove category"
        destructive
        loading={busyId !== null}
        onConfirm={() => {
          if (confirming) void onDelete(confirming.id, confirming.name);
        }}
      />
    </Dialog>
  );
}
