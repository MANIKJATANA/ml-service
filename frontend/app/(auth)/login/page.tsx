"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { mutate } from "swr";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { login } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";

export default function LoginPage() {
  const router = useRouter();
  const { toast } = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    try {
      const { must_change_password } = await login(email, password);
      await mutate("auth/me"); // drop any stale cached user before redirecting
      router.replace(must_change_password ? "/change-password" : "/");
      router.refresh();
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
      setSubmitting(false);
    }
  }

  return (
    <Card className="p-8">
      <div className="mb-6 flex flex-col gap-1">
        <h1 className="text-display-md text-ink">Sign in</h1>
        <p className="text-body text-ink-secondary">Welcome back.</p>
      </div>
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <Field label="Email" htmlFor="email">
          <Input
            id="email"
            name="email"
            type="email"
            autoFocus
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>
        <Field label="Password" htmlFor="password">
          <Input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        <Button type="submit" loading={submitting} className="mt-2 w-full">
          Sign in
        </Button>
      </form>
    </Card>
  );
}
