"use client";

import * as Popover from "@radix-ui/react-popover";
import { UserPlus, X } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { StudentRefAvatar } from "@/components/gallery/student-ref-avatar";
import { Button, buttonVariants } from "@/components/ui/button";
import { SearchInput } from "@/components/ui/search-input";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { useToast } from "@/components/ui/toast";
import { addMissedStudent, setMatchVerdict, undoCorrection } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { MediaAppearanceResponse } from "@/lib/api/types";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { useStudents } from "@/lib/hooks/use-students";
import { cn } from "@/lib/utils";

/** Staff-only editor for who appears in a photo — remove a wrong match (the X on each row)
 *  or add students the ML missed (the Add dropdown), for ANY photo (not just needs-review).
 *  Shared by the photo-detail page and the gallery lightbox so both stay in sync (BP5,
 *  decisions/0042). The caller owns the appearances fetch and passes `onChanged` (its SWR
 *  `mutate`) to refresh after each write. Every write is gated by `match:review` server-side.
 *
 *  Rejected matches are hidden here (they're "removed"); re-adding one via the dropdown
 *  brings it back. So the shown rows are the photo's EFFECTIVE students, and their ids are
 *  what the Add dropdown treats as already-present. */
export function AppearanceEditor({
  mediaId,
  appearances,
  isLoading,
  onChanged,
}: {
  mediaId: string;
  appearances: MediaAppearanceResponse[] | undefined;
  isLoading: boolean;
  onChanged: () => Promise<unknown>;
}) {
  const visible = useMemo(
    () => (appearances ?? []).filter((a) => a.verdict !== "rejected"),
    [appearances],
  );
  const presentIds = useMemo(() => visible.map((a) => a.student_id), [visible]);
  const hasConfidence = useMemo(() => visible.some((a) => a.confidence !== null), [visible]);

  return (
    <div className="flex flex-col gap-3">
      {isLoading ? (
        <Skeleton className="h-16 w-full" />
      ) : visible.length === 0 ? (
        <p className="text-body-sm text-ink-secondary">No students matched in this photo.</p>
      ) : (
        <ul className="flex flex-col">
          {visible.map((a) => (
            <AppearanceRow key={a.student_id} mediaId={mediaId} appearance={a} onChanged={onChanged} />
          ))}
        </ul>
      )}
      <AddStudents mediaId={mediaId} present={presentIds} onChanged={onChanged} />
      {/* BP21 (R3-S5-03): explain the % staff are asked to correct, and link the full explainer. */}
      <p className="text-body-sm text-ink-secondary">
        {hasConfidence
          ? "Percentages are how sure the match is — a low one is worth a second look. "
          : null}
        <Link
          href="/how-matching-works"
          className="rounded underline hover:text-ink-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          How photo matching works
        </Link>
      </p>
    </div>
  );
}

/** One student in the photo: name + confidence (or an "Added" tag) + an X to remove them
 *  (reject an ML match / undo a staff add). Re-add via the dropdown if removed by mistake. */
function AppearanceRow({
  mediaId,
  appearance,
  onChanged,
}: {
  mediaId: string;
  appearance: MediaAppearanceResponse;
  onChanged: () => Promise<unknown>;
}) {
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  const a = appearance;

  async function remove() {
    setBusy(true);
    try {
      if (a.verdict === "added") await undoCorrection(mediaId, a.student_id);
      else await setMatchVerdict(mediaId, a.student_id, "rejected");
      await onChanged();
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="flex items-center gap-2 border-b border-hairline py-2 last:border-b-0">
      {/* BP22: the student's reference face, so staff correct by looking, not guessing. */}
      <StudentRefAvatar studentId={a.student_id} name={a.name} className="size-8" />
      <span className="min-w-0 flex-1 truncate text-body-sm text-ink">{a.name}</span>
      {a.confidence !== null ? (
        <span className="tabular-nums text-body-sm text-ink-secondary">
          {Math.round(a.confidence * 100)}%
        </span>
      ) : (
        <StatusPill tone="info">Added</StatusPill>
      )}
      <button
        type="button"
        onClick={remove}
        disabled={busy}
        aria-label={`Remove ${a.name} from this photo`}
        className="shrink-0 rounded p-1 text-ink-muted transition-colors hover:text-error focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
      >
        <X className="size-4" aria-hidden="true" />
      </button>
    </li>
  );
}

/** "Add students" → a dismissible dropdown (Esc / click-away) with a searchable checklist of
 *  the roster minus who's already in the photo. Tick any number → "Add (N)". Always shown —
 *  even when everyone's added the dropdown just reads "Everyone's already in this photo." */
function AddStudents({
  mediaId,
  present,
  onChanged,
}: {
  mediaId: string;
  present: string[];
  onChanged: () => Promise<unknown>;
}) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  // Server-searched (BP9): the roster no longer loads in full — typing queries the students
  // list endpoint. We exclude whoever's already in the photo from the returned page.
  const debouncedQuery = useDebouncedValue(query.trim(), 250);
  const { items } = useStudents({ q: debouncedQuery || undefined });
  const options = useMemo(() => {
    const presentSet = new Set(present);
    return items.filter((s) => !presentSet.has(s.id));
  }, [items, present]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function onAdd() {
    const ids = [...selected];
    if (ids.length === 0) return;
    setBusy(true);
    try {
      const results = await Promise.allSettled(ids.map((id) => addMissedStudent(mediaId, id)));
      const failed = results.filter((r) => r.status === "rejected").length;
      await onChanged();
      // Close after adding (onOpenChange clears the query + selection); reopen with the Add
      // button to add more.
      setOpen(false);
      if (failed === 0) {
        toast(`Added ${plural(ids.length, "student")} to this photo.`, "success");
      } else {
        const ok = ids.length - failed;
        toast(
          ok > 0
            ? `Added ${plural(ok, "student")}; ${failed} couldn't be added. Try again.`
            : "Couldn't add those students. Please try again.",
          "error",
        );
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Popover.Root
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) {
          setQuery("");
          setSelected(new Set());
        }
      }}
    >
      <div className="border-t border-hairline pt-3">
        <Popover.Trigger
          className={cn(buttonVariants({ variant: "secondary", size: "sm" }))}
        >
          <UserPlus className="size-3.5" aria-hidden="true" />
          Add students
        </Popover.Trigger>
      </div>
      <Popover.Portal>
        <Popover.Content
          align="start"
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
          <ul className="max-h-48 overflow-y-auto rounded-button border border-hairline">
            {options.length === 0 ? (
              <li className="px-2 py-2 text-body-sm text-ink-secondary">
                {debouncedQuery ? "No students found." : "Search to add a student."}
              </li>
            ) : (
              options.map((s) => (
                <li key={s.id}>
                  <label className="flex cursor-pointer items-center gap-2 px-2 py-1.5 hover:bg-surface-2">
                    <input
                      type="checkbox"
                      checked={selected.has(s.id)}
                      onChange={() => toggle(s.id)}
                      className="size-4 shrink-0 accent-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    />
                    <span className="min-w-0 flex-1 truncate text-body-sm text-ink">{s.name}</span>
                  </label>
                </li>
              ))
            )}
          </ul>
          <Button
            size="sm"
            className="self-start"
            onClick={onAdd}
            loading={busy}
            disabled={selected.size === 0}
          >
            <UserPlus className="size-3.5" aria-hidden="true" />
            Add{selected.size > 0 ? ` (${selected.size})` : ""}
          </Button>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function plural(n: number, noun: string): string {
  return `${n} ${n === 1 ? noun : `${noun}s`}`;
}
