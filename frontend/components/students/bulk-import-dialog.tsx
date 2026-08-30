"use client";

import { Download, Upload } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogClose, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { StatusPill } from "@/components/ui/status-pill";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { bulkImportStudents } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { BulkStudentResult } from "@/lib/api/types";
import { type CsvStudentRow, EMAIL_RE, parseStudentCsv, saveCsv, toCsv } from "@/lib/csv";

const MAX_ROWS = 500; // matches the backend's per-request cap

const RESULT_TONE: Record<
  BulkStudentResult["status"],
  "success" | "warning" | "error" | "neutral"
> = {
  created: "success",
  duplicate: "warning",
  invalid: "error",
  error: "error",
};

const RESULT_LABEL: Record<BulkStudentResult["status"], string> = {
  created: "Created",
  duplicate: "Duplicate",
  invalid: "Invalid",
  error: "Error",
};

/** A09: a human reason for a non-created row. The backend populates `error` only for `invalid`
 *  rows; `duplicate` and generic `error` rows come back with `error === null`, so fall back to a
 *  static explanation. A `created` row shows no reason line. */
function resultReason(r: BulkStudentResult): string | null {
  if (r.status === "created") return null;
  if (r.error) return r.error;
  if (r.status === "duplicate") return "Already has an account — may exist at another school.";
  return "Couldn't be created — try again.";
}

type RowFlag = "ok" | "duplicate" | "invalid";

/** BP24: pre-flag the parsed rows before submit — an in-file duplicate email (case-insensitive)
 *  or an obviously invalid row (blank name/email or malformed email) — so problems are seen in
 *  the preview, not discovered only in the results. */
function flagRows(rows: CsvStudentRow[]): RowFlag[] {
  const seen = new Set<string>();
  return rows.map((r) => {
    const name = r.name.trim();
    const email = r.email.trim();
    if (!name || !email || !EMAIL_RE.test(email)) return "invalid";
    const key = email.toLowerCase();
    if (seen.has(key)) return "duplicate";
    seen.add(key);
    return "ok";
  });
}

const FLAG_TONE: Record<RowFlag, "success" | "warning" | "error"> = {
  ok: "success",
  duplicate: "warning",
  invalid: "error",
};
const FLAG_LABEL: Record<RowFlag, string> = {
  ok: "Ready",
  duplicate: "Duplicate",
  invalid: "Invalid",
};

type Phase = "pick" | "preview" | "results";

/** Import a class of students from a CSV of name+email (BP7d). Multi-step: choose file →
 *  preview the parsed rows → import (best-effort, server-side per-row) → results, with a
 *  one-time credentials download for the created accounts. Students are created photoless
 *  (pending) — add each one's reference photo afterwards to enroll their face. */
export function BulkImportDialog({ onImported }: { onImported: () => void }) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<Phase>("pick");
  const [rows, setRows] = useState<CsvStudentRow[]>([]);
  const [results, setResults] = useState<BulkStudentResult[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [downloaded, setDownloaded] = useState(false);
  const [confirmClose, setConfirmClose] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function reset() {
    setPhase("pick");
    setRows([]);
    setResults([]);
    setSubmitting(false);
    setDownloaded(false);
    setConfirmClose(false);
    if (inputRef.current) inputRef.current.value = "";
  }

  function forceClose() {
    setOpen(false);
    reset();
  }

  function handleOpenChange(next: boolean) {
    // Guard the shown-once credentials: block a close on the results step if accounts were
    // created and the passwords haven't been downloaded yet (BP18b).
    if (!next) {
      const created = results.filter((r) => r.status === "created").length;
      if (phase === "results" && created > 0 && !downloaded) {
        setConfirmClose(true); // keep the dialog open — confirm first
        return;
      }
      reset();
    }
    setOpen(next);
  }

  async function onFile(file: File) {
    let parsed: CsvStudentRow[];
    try {
      parsed = parseStudentCsv(await file.text());
    } catch {
      toast("Couldn't read that file.", "error");
      return;
    }
    if (parsed.length === 0) {
      toast("No student rows found — expected name and email columns.", "error");
      return;
    }
    if (parsed.length > MAX_ROWS) {
      toast(`Up to ${MAX_ROWS} students per import — split the file and try again.`, "error");
      return;
    }
    setRows(parsed);
    setPhase("preview");
  }

  async function submit() {
    setSubmitting(true);
    try {
      const res = await bulkImportStudents(
        rows.map((r) => ({
          name: r.name,
          email: r.email,
          class_name: r.className ?? null,
          mobile_number: r.mobile ?? null,
        })),
      );
      setResults(res.results);
      setPhase("results");
      onImported();
      const created = res.results.filter((r) => r.status === "created").length;
      toast(
        `Imported ${created} of ${res.results.length} students.`,
        created > 0 ? "success" : "info",
      );
    } catch (err) {
      toast(isApiError(err) ? err.message : "Import failed. Please try again.", "error");
    } finally {
      setSubmitting(false);
    }
  }

  function downloadCredentials() {
    const created = results.filter((r) => r.status === "created" && r.temp_password);
    saveCsv(
      "student-credentials.csv",
      toCsv(
        ["name", "email", "temporary_password"],
        created.map((r) => [r.name, r.email, r.temp_password ?? ""]),
      ),
    );
    setDownloaded(true);
  }

  // BP24: export the rows that DIDN'T import (duplicate/invalid/error) as a name+email CSV, so
  // the admin can fix the typos and re-import — no hand-transcribing (R3-A2-11).
  function downloadSkipped() {
    const skipped = results.filter((r) => r.status !== "created");
    saveCsv(
      "skipped-rows.csv",
      toCsv(["name", "email"], skipped.map((r) => [r.name, r.email])),
    );
  }

  const createdCount = results.filter((r) => r.status === "created").length;
  const skippedCount = results.length - createdCount;
  // BP24: show a Class column in the preview only when the CSV actually carried one.
  const hasClasses = rows.some((r) => r.className);
  // Phase 0: likewise show a Mobile column only when the CSV carried a mobile/phone column.
  const hasMobiles = rows.some((r) => r.mobile);
  // BP24: pre-flag duplicate/invalid rows in the preview (the server still validates).
  const flags = flagRows(rows);
  const willSkip = flags.filter((f) => f !== "ok").length;

  return (
    <>
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogTrigger asChild>
          <Button variant="secondary">
            <Upload className="size-4" aria-hidden="true" />
            Import CSV
          </Button>
        </DialogTrigger>
        <DialogContent
          title="Import students from CSV"
          description="A CSV with name and email columns (add an optional class column to sort them into classes, and an optional mobile/phone column for WhatsApp). Students are created without a photo (pending) — add each reference photo afterwards to enroll their face."
        >
          {phase === "pick" ? (
            <div className="flex flex-col gap-4">
              <p className="text-body-sm text-ink-secondary">
                The first row may be a header (<code>name,email,class,mobile</code>); otherwise
                the first column is the name and the second is the email. Add a{" "}
                <code>class</code> header to sort students into classes (created automatically by
                name), and a <code>mobile</code> or <code>phone</code> header for the WhatsApp
                contact.
              </p>
              <label
                className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-button border border-dashed border-hairline-strong bg-surface px-4 py-10 text-center transition-colors hover:bg-surface-2 focus-within:outline-none focus-within:ring-2 focus-within:ring-ring"
              >
                <Upload className="size-6 text-ink-muted" aria-hidden="true" />
                <span className="text-body-sm text-ink-secondary">
                  Choose a <span className="font-medium text-accent-hover">.csv</span> file
                </span>
                <input
                  ref={inputRef}
                  type="file"
                  accept=".csv,text/csv"
                  className="sr-only"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) void onFile(f);
                    // Clear so re-picking the SAME file after a rejected parse still fires.
                    e.target.value = "";
                  }}
                />
              </label>
            </div>
          ) : phase === "preview" ? (
            <div className="flex flex-col gap-4">
              <p role="status" className="text-body-sm text-ink-secondary">
                {rows.length - willSkip} of {rows.length}{" "}
                {rows.length === 1 ? "row" : "rows"} ready to import
                {willSkip > 0
                  ? ` — ${willSkip} flagged (duplicate or invalid) will be skipped.`
                  : "."}
              </p>
              <div className="max-h-64 overflow-y-auto rounded-card border border-hairline">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Email</TableHead>
                      {hasClasses ? <TableHead>Class</TableHead> : null}
                      {hasMobiles ? <TableHead>Mobile</TableHead> : null}
                      <TableHead>Status</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.map((r, i) => (
                      <TableRow key={i}>
                        <TableCell>{r.name || "—"}</TableCell>
                        <TableCell>{r.email || "—"}</TableCell>
                        {hasClasses ? (
                          <TableCell className="text-ink-secondary">
                            {r.className || "—"}
                          </TableCell>
                        ) : null}
                        {hasMobiles ? (
                          <TableCell className="text-ink-secondary">
                            {r.mobile || "—"}
                          </TableCell>
                        ) : null}
                        <TableCell>
                          {/* BP24: pre-flag duplicates/invalids before submit. */}
                          <StatusPill tone={FLAG_TONE[flags[i]]}>
                            {FLAG_LABEL[flags[i]]}
                          </StatusPill>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              <div className="mt-1 flex justify-end gap-2">
                <Button type="button" variant="secondary" onClick={reset} disabled={submitting}>
                  Choose another file
                </Button>
                <Button type="button" onClick={submit} loading={submitting}>
                  Import {rows.length} {rows.length === 1 ? "student" : "students"}
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              <p role="status" className="text-body-sm text-ink-secondary">
                {createdCount} created
                {results.length - createdCount > 0
                  ? `, ${results.length - createdCount} skipped`
                  : ""}
                . Download the temporary passwords now — they won&apos;t be shown again. Add
                each student&apos;s photo afterwards to enroll their face.
              </p>
              <div className="max-h-64 overflow-y-auto rounded-card border border-hairline">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Email</TableHead>
                      <TableHead>Result</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {results.map((r, i) => (
                      <TableRow key={i}>
                        <TableCell>{r.email || "—"}</TableCell>
                        <TableCell>
                          <div className="flex flex-col gap-1">
                            <StatusPill tone={RESULT_TONE[r.status]}>
                              {RESULT_LABEL[r.status]}
                            </StatusPill>
                            {/* A09: explain WHY a row didn't import — the backend populates
                                `error` only for `invalid` rows; duplicate/error get a static
                                fallback. `created` rows show no reason line. */}
                            {resultReason(r) ? (
                              <span className="text-body-sm text-ink-secondary">
                                {resultReason(r)}
                              </span>
                            ) : null}
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              {/* Download credentials is the emphasized action — the temp passwords are shown
                  once. BP24: also export the skipped rows to fix-and-reimport. */}
              <div className="mt-1 flex flex-wrap justify-end gap-2">
                <DialogClose asChild>
                  <Button type="button" variant="secondary">
                    Done
                  </Button>
                </DialogClose>
                {skippedCount > 0 ? (
                  <Button type="button" variant="secondary" onClick={downloadSkipped}>
                    <Download className="size-4" aria-hidden="true" />
                    Download skipped rows
                  </Button>
                ) : null}
                {createdCount > 0 ? (
                  <Button type="button" onClick={downloadCredentials}>
                    <Download className="size-4" aria-hidden="true" />
                    Download credentials
                  </Button>
                ) : null}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={confirmClose}
        onOpenChange={setConfirmClose}
        title="Close without downloading?"
        description="You haven't downloaded the temporary passwords. They won't be shown again — you'd have to send each student a new one individually."
        confirmLabel="Close anyway"
        onConfirm={forceClose}
      />
    </>
  );
}
