"use client";

import { Upload } from "lucide-react";
import { useRef, useState } from "react";

import {
  BulkCredentialsDialog,
  type CredentialRow,
} from "@/components/credentials/bulk-credentials-dialog";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";
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
import { bulkCreateStaff } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import { EMAIL_RE, parseStaffCsv } from "@/lib/csv";

const MAX_EMAILS = 100; // matches the backend's per-request cap (_MAX_BULK_STAFF)

// A client heads-up before submit — the server validates authoritatively (a malformed email is a
// per-row `invalid`, a duplicate a per-row `duplicate`; neither aborts the batch).
type Flag = "ok" | "duplicate" | "invalid";
const FLAG_TONE: Record<Flag, "success" | "warning" | "error"> = {
  ok: "success",
  duplicate: "warning",
  invalid: "error",
};
const FLAG_LABEL: Record<Flag, string> = {
  ok: "Ready",
  duplicate: "Duplicate",
  invalid: "Invalid",
};

/** Pre-flag each parsed email — an in-file duplicate (case-insensitive) or an obviously malformed
 *  one — so problems show in the preview, not only in the results. */
function flagEmails(emails: string[]): Flag[] {
  const seen = new Set<string>();
  return emails.map((email) => {
    if (!EMAIL_RE.test(email.trim())) return "invalid";
    const key = email.trim().toLowerCase();
    if (seen.has(key)) return "duplicate";
    seen.add(key);
    return "ok";
  });
}

type Phase = "pick" | "preview";

/**
 * Invite a batch of teachers from a CSV of emails (BP27b). Multi-step: choose file → preview the
 * parsed emails (with a client heads-up on duplicates/invalids) → invite (best-effort, server-side
 * per-row) → the shared `BulkCredentialsDialog` shows the ONE-TIME temp passwords for the created
 * accounts. On done the parent refreshes the staff roster (staff-bulk creates rows).
 */
export function BulkInviteDialog({ onInvited }: { onInvited: () => void }) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<Phase>("pick");
  const [emails, setEmails] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  // The shown-once credentials (null = the results dialog is closed → the passwords are dropped).
  const [creds, setCreds] = useState<CredentialRow[] | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function reset() {
    setPhase("pick");
    setEmails([]);
    setSubmitting(false);
    if (inputRef.current) inputRef.current.value = "";
  }

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) reset();
  }

  async function onFile(file: File) {
    let parsed: string[];
    try {
      parsed = parseStaffCsv(await file.text());
    } catch {
      toast("Couldn't read that file.", "error");
      return;
    }
    if (parsed.length === 0) {
      toast("No emails found — expected a column of email addresses.", "error");
      return;
    }
    if (parsed.length > MAX_EMAILS) {
      toast(`Up to ${MAX_EMAILS} teachers per import — split the file and try again.`, "error");
      return;
    }
    setEmails(parsed);
    setPhase("preview");
  }

  async function submit() {
    setSubmitting(true);
    try {
      const res = await bulkCreateStaff(emails);
      const created = res.results.filter((r) => r.status === "created").length;
      const capped = res.results.filter((r) => r.status === "limit_reached").length;
      // Show the ONE-TIME passwords (present only on `created` rows) in the shared dialog, then
      // close this importer so only the credentials dialog is up.
      setCreds(
        res.results.map((r) => ({
          label: r.email,
          status: r.status,
          tempPassword: r.temp_password,
          detail: r.error, // surface the server's short reason for an invalid/error row (BP27b R2)
        })),
      );
      handleOpenChange(false);
      onInvited(); // the staff roster gained rows — refresh it
      toast(
        `Created ${created} of ${res.results.length} teacher${res.results.length === 1 ? "" : "s"}.${
          capped > 0 ? ` ${capped} at capacity.` : ""
        }`,
        created > 0 ? "success" : "info",
      );
    } catch (err) {
      // A whole-batch failure (e.g. a suspended school → 400, or the session expired).
      toast(isApiError(err) ? err.message : "Import failed. Please try again.", "error");
    } finally {
      setSubmitting(false);
    }
  }

  const flags = flagEmails(emails);
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
          title="Invite teachers from CSV"
          description="A CSV with a column of email addresses. We generate a temporary password for each — shown once, right after importing."
        >
          {phase === "pick" ? (
            <div className="flex flex-col gap-4">
              <p className="text-body-sm text-ink-secondary">
                The first row may be a header (<code>email</code>); otherwise the first column is
                the email. Extra columns are ignored.
              </p>
              <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-button border border-dashed border-hairline-strong bg-surface px-4 py-10 text-center transition-colors hover:bg-surface-2 focus-within:outline-none focus-within:ring-2 focus-within:ring-ring">
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
          ) : (
            <div className="flex flex-col gap-4">
              <p role="status" className="text-body-sm text-ink-secondary">
                {emails.length - willSkip} of {emails.length}{" "}
                {emails.length === 1 ? "email" : "emails"} ready to invite
                {willSkip > 0
                  ? ` — ${willSkip} flagged (duplicate or invalid) will be skipped.`
                  : "."}
              </p>
              <div className="max-h-64 overflow-y-auto rounded-card border border-hairline">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Email</TableHead>
                      <TableHead>Status</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {emails.map((email, i) => (
                      <TableRow key={i}>
                        <TableCell className="break-all">{email || "—"}</TableCell>
                        <TableCell>
                          <StatusPill tone={FLAG_TONE[flags[i]]}>{FLAG_LABEL[flags[i]]}</StatusPill>
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
                  Invite {emails.length} {emails.length === 1 ? "teacher" : "teachers"}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <BulkCredentialsDialog
        title="Temporary passwords"
        description="Share each password securely — they won't be shown again. Teachers set their own on first sign-in."
        results={creds}
        onClose={() => setCreds(null)}
      />
    </>
  );
}
