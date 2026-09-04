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

/** The platform WhatsApp form — the DB-controlled fields (sender number, token, approved template,
 *  interim number), the SOLE WhatsApp config (0099: schools no longer configure WhatsApp). Seeded
 *  from the loaded config so the current DB values are visible. Remounted by `key` on save. The
 *  token field is WRITE-ONLY — it starts blank and a blank field on save leaves the stored token
 *  unchanged (the API never returns the token); the sender/template/interim fields show their
 *  current value and clearing one (saving it blank) clears it server-side. */
function PlatformWhatsAppForm({
  config,
  onSaved,
}: {
  config: WhatsAppPlatformConfigResponse;
  onSaved: () => Promise<unknown>;
}) {
  const { toast } = useToast();
  const [senderNumber, setSenderNumber] = useState(config.sender_number ?? "");
  const [token, setToken] = useState(""); // always blank; write-only
  const [templateName, setTemplateName] = useState(config.template_name ?? "");
  const [interimNumber, setInterimNumber] = useState(config.interim_test_number ?? "");
  const [saving, setSaving] = useState(false);

  const tokenHint = config.token_set
    ? `A token is set (ending ${config.token_last4 ?? "••••"}). Leave blank to keep it, or paste a new one to replace it.`
    : "No token set yet — paste your Meta access token (a temporary token expires ~daily).";

  // The interim path is gated on the interim number being present (there is no separate toggle):
  // while it has a value, every send is diverted to it.
  const interimOn = interimNumber.trim().length > 0;

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    try {
      await updateWhatsAppPlatformConfig({
        // Blank token → null → the stored token is left unchanged (write-only).
        meta_access_token: token.trim() || null,
        // These are visible fields: send the value as-is, so "" clears them server-side.
        sender_number: senderNumber.trim(),
        template_name: templateName.trim(),
        interim_test_number: interimNumber.trim(),
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
        <Field
          label="Sender number"
          htmlFor="wa-sender"
          hint="The Meta sender phone-number ID (from Meta → WhatsApp → API Setup — the numeric 'Phone number ID', not the +country number). Stored in the DB only — this is the one place it's set (no .env)."
        >
          <Input
            id="wa-sender"
            inputMode="numeric"
            maxLength={64}
            placeholder="e.g. 106540388866237"
            value={senderNumber}
            onChange={(e) => setSenderNumber(e.target.value)}
            disabled={saving}
          />
        </Field>

        <Field label="Meta access token" htmlFor="wa-token" hint={tokenHint}>
          <Input
            id="wa-token"
            type="password"
            autoComplete="off"
            placeholder={config.token_set ? "•••••••• (unchanged)" : "Paste the Meta access token"}
            value={token}
            onChange={(e) => setToken(e.target.value)}
            disabled={saving}
          />
        </Field>

        <Field
          label="Template name"
          htmlFor="wa-template"
          hint="The approved WhatsApp message template used for real (non-interim) sends. For Meta this is the template's NAME; for Gupshup its template ID/UUID. A send fails until this is set."
        >
          <Input
            id="wa-template"
            placeholder="e.g. event_photos_util"
            value={templateName}
            onChange={(e) => setTemplateName(e.target.value)}
            disabled={saving}
          />
        </Field>

        <Field
          label="Interim test number"
          htmlFor="wa-interim-number"
          hint="Where interim test sends go, E.164 digits (e.g. 919306229596). When set, every send is diverted here (not to students). Clear it for normal delivery. Use a number that has messaged your WhatsApp business in the last 24h."
        >
          <Input
            id="wa-interim-number"
            inputMode="tel"
            maxLength={32}
            placeholder="919306229596"
            value={interimNumber}
            onChange={(e) => setInterimNumber(e.target.value)}
            disabled={saving}
          />
        </Field>

        {/* A live warning while an interim number is set — it diverts ALL sends to the test number. */}
        {interimOn ? (
          <p
            role="alert"
            className="rounded-button bg-warning-soft px-3 py-2 text-body-sm font-medium text-warning-strong"
          >
            ⚠️ Interim test mode is ON (an interim number is set) — every &ldquo;Send on
            WhatsApp&rdquo; across all schools goes to that test number, <b>not to students</b>.
            Clear this field for normal delivery.
          </p>
        ) : null}

        <p className="rounded-button bg-surface px-3 py-2 text-body-sm text-ink-secondary">
          Schools no longer configure WhatsApp — you control it all here. These settings are stored
          in the database and take effect on the next send — no restart needed. The token is stored
          securely and never shown again. Interim mode is for
          testing — it delivers only inside WhatsApp&rsquo;s 24-hour window and to the test number,
          not to students. If the test number hasn&rsquo;t messaged your WhatsApp business in the
          last 24h, a send is accepted but won&rsquo;t arrive (and the app will still say
          &ldquo;Sent&rdquo;).
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
        description="Platform-wide WhatsApp settings — the sender number, Meta access token, approved template, and interim test number. Schools no longer configure WhatsApp; you control it all here. All stored in the database and editable here (no restart)."
      />

      {isLoading && !config ? (
        <Card className="flex flex-col gap-3 p-6">
          {[0, 1, 2, 3].map((i) => (
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
