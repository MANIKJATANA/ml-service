"use client";

import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { updateWhatsAppPlatformConfig } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { WhatsAppPlatformConfigResponse } from "@/lib/api/types";
import { useWhatsAppPlatformConfig } from "@/lib/hooks/use-whatsapp-platform-config";

/** The platform WhatsApp form, seeded from the loaded config. Remounted by `key` on save (the
 *  repo's no-setState-in-effect pattern). The token field is WRITE-ONLY — it starts blank and a
 *  blank field on save leaves the stored token unchanged (the API never returns the token). */
function PlatformWhatsAppForm({
  config,
  onSaved,
}: {
  config: WhatsAppPlatformConfigResponse;
  onSaved: () => Promise<unknown>;
}) {
  const { toast } = useToast();
  const [token, setToken] = useState(""); // always blank; write-only
  const [interimNumber, setInterimNumber] = useState(config.interim_test_number ?? "");
  const [interimMode, setInterimMode] = useState(config.interim_mode);
  const [saving, setSaving] = useState(false);

  const tokenHint = config.token_set
    ? `A token is set (ending ${config.token_last4 ?? "••••"}). Leave blank to keep it, or paste a new one to replace it.`
    : "No token set yet — paste your Meta access token (a temporary token expires ~daily).";

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    try {
      await updateWhatsAppPlatformConfig({
        // Blank token → null → the stored token is left unchanged.
        meta_access_token: token.trim() || null,
        interim_test_number: interimNumber.trim() || null,
        interim_mode: interimMode,
      });
      await onSaved();
      setToken(""); // never keep the pasted secret in state after a save
      toast("WhatsApp platform settings saved.", "success");
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card className="p-6">
      <form onSubmit={onSubmit} className="flex max-w-xl flex-col gap-5">
        <Field label="Meta access token" htmlFor="wa-token" hint={tokenHint}>
          <Input
            id="wa-token"
            type="password"
            autoComplete="off"
            placeholder={config.token_set ? "•••••••• (unchanged)" : "Paste the Meta access token"}
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
        </Field>

        <Field
          label="Interim test number"
          htmlFor="wa-interim-number"
          hint="Where interim test sends go, E.164 digits (e.g. 919306229596). Use a number that has messaged your WhatsApp business in the last 24h."
        >
          <Input
            id="wa-interim-number"
            inputMode="tel"
            maxLength={32}
            placeholder="919306229596"
            value={interimNumber}
            onChange={(e) => setInterimNumber(e.target.value)}
          />
        </Field>

        {/* Interim mode toggle — a testing switch; its impact is spelled out. */}
        <div className="flex flex-col gap-1">
          <label htmlFor="wa-interim-mode" className="flex items-start gap-3">
            <input
              id="wa-interim-mode"
              type="checkbox"
              checked={interimMode}
              onChange={(e) => setInterimMode(e.target.checked)}
              aria-describedby="wa-interim-mode-hint"
              className="mt-0.5 size-4 shrink-0 rounded accent-accent-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <span className="text-body-sm font-medium text-ink">Interim test mode</span>
          </label>
          <p id="wa-interim-mode-hint" className="text-body-sm text-ink-secondary">
            When ON, every &ldquo;Send on WhatsApp&rdquo; sends a text + the real photos to the test
            number above (for testing) instead of the student. Turn OFF for the normal flow.
          </p>
        </div>

        {/* A live warning only while interim mode is ON — it diverts ALL sends to the test number. */}
        {interimMode ? (
          <p
            role="alert"
            className="rounded-button bg-warning-soft px-3 py-2 text-body-sm font-medium text-warning-strong"
          >
            ⚠️ Interim test mode is ON — every &ldquo;Send on WhatsApp&rdquo; across all schools goes
            to the test number, <b>not to students</b>. Turn this OFF for normal delivery.
          </p>
        ) : null}

        <p className="rounded-button bg-surface px-3 py-2 text-body-sm text-ink-secondary">
          The token is stored securely and never shown again. Interim mode is for testing — it
          delivers only inside WhatsApp&rsquo;s 24-hour window and to the test number, not to students.
          If the test number hasn&rsquo;t messaged your WhatsApp business in the last 24h, a send is
          accepted but won&rsquo;t arrive (and the app will still say &ldquo;Sent&rdquo;).
        </p>

        <div className="flex justify-end">
          <Button type="submit" loading={saving}>
            Save settings
          </Button>
        </div>
      </form>
    </Card>
  );
}

function PlatformWhatsAppInner() {
  const { config, isLoading, error, mutate } = useWhatsAppPlatformConfig();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="WhatsApp"
        description="Platform-wide WhatsApp settings — the Meta access token and the interim test-send controls."
      />

      {isLoading && !config ? (
        <Card className="flex flex-col gap-3 p-6">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </Card>
      ) : error || !config ? (
        <EmptyState
          role="alert"
          title="Couldn't load WhatsApp platform settings"
          description="Something went wrong reaching the server."
          action={
            <Button variant="secondary" onClick={() => void mutate()}>
              Retry
            </Button>
          }
        />
      ) : (
        <PlatformWhatsAppForm key={config.updated_at} config={config} onSaved={() => mutate()} />
      )}
    </div>
  );
}

export default function PlatformWhatsAppPage() {
  // The (platform) layout's AuthGuard already restricts this group to platform_admin; the backend
  // also gates on SCHOOL_MANAGE.
  return <PlatformWhatsAppInner />;
}
