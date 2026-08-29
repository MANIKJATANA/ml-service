"use client";

import { Check, Copy, Download } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogClose, DialogContent } from "@/components/ui/dialog";
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
import { saveCsv, toCsv } from "@/lib/csv";
import { copyToClipboard } from "@/lib/utils";

/** One row's outcome for the shared credentials dialog (BP27b). `tempPassword` is the ONE-TIME
 *  plaintext — present ONLY on a success row; the dialog shows + exports it, then drops it on
 *  close. `status` is the raw backend verdict (student: sent/error; staff:
 *  created/duplicate/invalid/limit_reached/error). */
export interface CredentialRow {
  label: string; // the student/teacher email
  status: string;
  tempPassword?: string | null;
  detail?: string | null; // a short server reason for an invalid/error row (BP27b)
}

const TONE: Record<string, "success" | "warning" | "error" | "neutral"> = {
  sent: "success",
  created: "success",
  duplicate: "warning",
  limit_reached: "warning",
  invalid: "error",
  error: "error",
};

const RESULT_LABEL: Record<string, string> = {
  sent: "Sent",
  created: "Created",
  duplicate: "Duplicate",
  limit_reached: "At capacity",
  invalid: "Invalid",
  error: "Error",
};

/**
 * Shows the ONE-TIME temporary passwords from a bulk resend/invite (BP27b), shared by the student
 * bulk-resend flow and the staff CSV bulk-invite. Controlled: pass `title`/`results` to open,
 * `onClose` clears it. Each success row shows an inline copyable password; "Download credentials"
 * exports every credential-bearing row as a CSV. A close is guarded (a ConfirmDialog) while any
 * credential hasn't been downloaded — mirroring the single-invite + student-import dialogs — so a
 * stray dismissal can't lose the shown-once secrets. The plaintext lives only in `results`; on
 * close `reset()` drops it (the caller passes `results: null`).
 */
export function BulkCredentialsDialog({
  title,
  description,
  results,
  onClose,
}: {
  title: string;
  description?: string;
  results: CredentialRow[] | null;
  onClose: () => void;
}) {
  const { toast } = useToast();
  const [downloaded, setDownloaded] = useState(false);
  const [confirmClose, setConfirmClose] = useState(false);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);

  function reset() {
    setDownloaded(false);
    setConfirmClose(false);
    setCopiedIdx(null);
    onClose(); // the caller sets results=null → the passwords leave component state
  }

  async function copyRow(i: number, password: string) {
    if (await copyToClipboard(password)) {
      setCopiedIdx(i);
      toast("Temporary password copied.", "success");
    } else {
      toast("Couldn't copy — select the password and copy it manually.", "error");
    }
  }

  // Only success rows carry a plaintext password.
  const withPassword = (results ?? []).filter((r) => r.tempPassword);
  const hasSecrets = withPassword.length > 0;
  const hasDuplicate = (results ?? []).some((r) => r.status === "duplicate");

  function requestClose() {
    // Guard the shown-once credentials: if any password hasn't been downloaded, confirm first.
    // When every row is error/duplicate/limit_reached (no secrets), close freely.
    if (!hasSecrets || downloaded) reset();
    else setConfirmClose(true);
  }

  function downloadCredentials() {
    saveCsv(
      "credentials.csv",
      toCsv(
        ["email", "temporary_password"],
        withPassword.map((r) => [r.label, r.tempPassword ?? ""]),
      ),
    );
    setDownloaded(true);
  }

  return (
    <>
      <Dialog
        open={results !== null}
        onOpenChange={(open) => {
          if (!open) requestClose();
        }}
      >
        <DialogContent title={title} description={description}>
          {results ? (
            <div className="flex flex-col gap-4">
              <p role="status" className="text-body-sm text-ink-secondary">
                {hasSecrets
                  ? `Copy or download the ${withPassword.length} temporary password${
                      withPassword.length === 1 ? "" : "s"
                    } now — they won't be shown again.`
                  : "No new passwords were issued."}
              </p>
              <div className="max-h-72 overflow-y-auto rounded-card border border-hairline">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Email</TableHead>
                      <TableHead>Result</TableHead>
                      <TableHead>Temporary password</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {results.map((r, i) => (
                      <TableRow key={i}>
                        <TableCell className="break-all">{r.label || "—"}</TableCell>
                        <TableCell>
                          <div className="flex flex-col gap-1">
                            <StatusPill tone={TONE[r.status] ?? "neutral"}>
                              {RESULT_LABEL[r.status] ?? r.status}
                            </StatusPill>
                            {r.detail ? (
                              <span className="text-body-sm text-ink-secondary">{r.detail}</span>
                            ) : null}
                          </div>
                        </TableCell>
                        <TableCell>
                          {r.tempPassword ? (
                            <div className="flex items-center gap-2">
                              <code className="min-w-0 flex-1 select-all break-all font-mono text-body-sm text-ink">
                                {r.tempPassword}
                              </code>
                              <Button
                                type="button"
                                size="sm"
                                variant="ghost"
                                className="shrink-0"
                                aria-label={`Copy password for ${r.label}`}
                                onClick={() => copyRow(i, r.tempPassword as string)}
                              >
                                {copiedIdx === i ? (
                                  <Check className="size-4" aria-hidden="true" />
                                ) : (
                                  <Copy className="size-4" aria-hidden="true" />
                                )}
                              </Button>
                            </div>
                          ) : (
                            <span className="text-ink-secondary">—</span>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              {hasDuplicate ? (
                <p className="text-body-sm text-ink-secondary">
                  &ldquo;Duplicate&rdquo; means that email already has an account (here or at
                  another school) &mdash; it wasn&apos;t changed.
                </p>
              ) : null}
              <div className="mt-1 flex flex-wrap justify-end gap-2">
                <DialogClose asChild>
                  <Button type="button" variant="secondary">
                    Done
                  </Button>
                </DialogClose>
                {hasSecrets ? (
                  <Button type="button" onClick={downloadCredentials}>
                    <Download className="size-4" aria-hidden="true" />
                    Download credentials
                  </Button>
                ) : null}
              </div>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={confirmClose}
        onOpenChange={setConfirmClose}
        title="Close without downloading?"
        description="You haven't downloaded the temporary passwords. They won't be shown again — you'd have to send each person a new one individually."
        confirmLabel="Close anyway"
        onConfirm={reset}
      />
    </>
  );
}
