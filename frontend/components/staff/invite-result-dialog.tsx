"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { copyToClipboard } from "@/lib/utils";

export interface Invite {
  email: string;
  tempPassword: string;
}

/** Shows a freshly-provisioned / re-invited account's ONE-TIME temp password with a copy
 *  button (BP7c). Controlled: set `invite` to open, `onClose` clears it. Shared by the
 *  staff page (teachers) and the platform school detail (admins). The plaintext password
 *  is never persisted client-side beyond this dialog's lifetime. */
export function InviteResultDialog({
  invite,
  onClose,
}: {
  invite: Invite | null;
  onClose: () => void;
}) {
  const { toast } = useToast();
  const [copied, setCopied] = useState(false);
  const [confirmClose, setConfirmClose] = useState(false);

  function close() {
    setCopied(false);
    setConfirmClose(false);
    onClose();
  }

  function requestClose() {
    // Guard a one-time password against a stray Esc / overlay-click / early Done: if it
    // hasn't been copied, confirm before it's lost for good (BP18b).
    if (copied) close();
    else setConfirmClose(true);
  }

  async function copy() {
    if (!invite) return;
    if (await copyToClipboard(invite.tempPassword)) {
      setCopied(true);
      toast("Temporary password copied.", "success");
    } else {
      toast("Couldn't copy — select the password and copy it manually.", "error");
    }
  }

  return (
    <>
      <Dialog
        open={invite !== null}
        onOpenChange={(open) => {
          if (!open) requestClose();
        }}
      >
        <DialogContent
          title="Temporary password"
          description="Copy this now and share it securely — it won't be shown again. They'll set their own password on first sign-in."
        >
          {invite ? (
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <span className="text-body-sm text-ink-secondary">{invite.email}</span>
                <div className="flex items-center gap-2">
                  <code className="min-w-0 flex-1 select-all break-all rounded-button border border-hairline bg-surface px-3 py-2 font-mono text-body text-ink">
                    {invite.tempPassword}
                  </code>
                  <Button type="button" variant="secondary" onClick={copy} className="shrink-0">
                    {copied ? (
                      <Check className="size-4" aria-hidden="true" />
                    ) : (
                      <Copy className="size-4" aria-hidden="true" />
                    )}
                    {copied ? "Copied" : "Copy"}
                  </Button>
                </div>
              </div>
              <div className="flex justify-end">
                <Button type="button" onClick={requestClose}>
                  Done
                </Button>
              </div>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={confirmClose}
        onOpenChange={setConfirmClose}
        title="Close without copying?"
        description="You haven't copied the temporary password. It won't be shown again — you'd have to send a new one."
        confirmLabel="Close anyway"
        onConfirm={close}
      />
    </>
  );
}
