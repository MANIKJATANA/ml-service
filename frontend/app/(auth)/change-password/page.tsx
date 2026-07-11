"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { mutate } from "swr";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { changePassword } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";

export default function ChangePasswordPage() {
  const router = useRouter();
  const { toast } = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [newError, setNewError] = useState<string>();
  const [confirmError, setConfirmError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const tooShort = next.length < 8 ? "Must be at least 8 characters." : undefined;
    const mismatch = next !== confirm ? "Passwords don't match." : undefined;
    setNewError(tooShort);
    setConfirmError(mismatch);
    if (tooShort || mismatch) return;

    setSubmitting(true);
    try {
      await changePassword(current, next);
      await mutate("auth/me"); // must_change_password is now cleared server-side
      toast("Password updated.", "success");
      router.replace("/");
      router.refresh();
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
      setSubmitting(false);
    }
  }

  return (
    <Card className="p-8">
      <div className="mb-6 flex flex-col gap-1">
        <h1 className="text-display-md text-ink">Change password</h1>
        <p className="text-body text-ink-secondary">Set a new password to continue.</p>
      </div>
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <Field label="Current password" htmlFor="current">
          <Input
            id="current"
            name="current"
            type="password"
            autoComplete="current-password"
            required
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
          />
        </Field>
        <Field label="New password" htmlFor="new" hint="At least 8 characters." error={newError}>
          <Input
            id="new"
            name="new"
            type="password"
            autoComplete="new-password"
            required
            invalid={Boolean(newError)}
            value={next}
            onChange={(e) => {
              setNext(e.target.value);
              setNewError(undefined);
              setConfirmError(undefined);
            }}
          />
        </Field>
        <Field label="Confirm new password" htmlFor="confirm" error={confirmError}>
          <Input
            id="confirm"
            name="confirm"
            type="password"
            autoComplete="new-password"
            required
            invalid={Boolean(confirmError)}
            value={confirm}
            onChange={(e) => {
              setConfirm(e.target.value);
              setConfirmError(undefined);
            }}
          />
        </Field>
        <Button type="submit" loading={submitting} className="mt-2 w-full">
          Update password
        </Button>
      </form>
    </Card>
  );
}
