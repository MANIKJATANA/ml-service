"use client";

import { type FormEvent, useState } from "react";

import { RoleGate } from "@/components/role-gate";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { updateWhatsAppConfig } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { WhatsAppConfigResponse } from "@/lib/api/types";
import { useWhatsAppConfig } from "@/lib/hooks/use-whatsapp-config";

/** The settings form, seeded from the loaded config. The parent remounts it with a `key` when
 *  the config identity changes (after a save revalidates), so state comes straight from props —
 *  no setState-in-effect (the repo's ClassFormDialog pattern). */
function WhatsAppForm({
  config,
  onSaved,
}: {
  config: WhatsAppConfigResponse;
  onSaved: () => Promise<unknown>;
}) {
  const { toast } = useToast();
  const [enabled, setEnabled] = useState(config.enabled);
  const [senderNumber, setSenderNumber] = useState(config.sender_number ?? "");
  const [templateName, setTemplateName] = useState(config.template_name ?? "");
  const [businessName, setBusinessName] = useState(config.business_name ?? "");
  const [saving, setSaving] = useState(false);

  // Truthful in all three states: using the shared number (with/without a configured default),
  // or this school has its own number set.
  // The active provider drives two fields. Gupshup matches a template by UUID and uses the
  // per-school sender number; Meta matches by the template NAME and takes the sender from the
  // platform's phone-number ID (env) — so under Meta the "Sender number" field is not used.
  const isMeta = config.provider === "meta";

  const sharedHint = isMeta
    ? "Not used with Meta — the sender is the platform's Meta phone number (set via BE_WHATSAPP_META_PHONE_NUMBER_ID)."
    : config.using_shared_number
      ? config.effective_sender_number
        ? `Leave blank to use the shared app number (${config.effective_sender_number}).`
        : "No shared app number is configured yet — enter your school's approved WhatsApp sender number."
      : "Clear this to fall back to the shared app number.";
  const templateLabel = isMeta ? "Template name" : "Template ID";
  const templateHint = isMeta
    ? "The approved template's NAME from your Meta WhatsApp Manager (Meta matches by name, not an ID). Photos won't send without an approved template."
    : "The approved template's ID — a UUID from your Gupshup dashboard (e.g. c6aecef6-bcb0-4fb1-8100-28c094e3bc6b), NOT its display name. Photos won't send without the exact ID of an approved template.";
  const templatePlaceholder = isMeta
    ? "event_photos"
    : "c6aecef6-bcb0-4fb1-8100-28c094e3bc6b";
  const providerLabel =
    config.provider === "meta"
      ? "Meta WhatsApp Cloud API"
      : config.provider === "gupshup"
        ? "Gupshup"
        : "Test sender (no messages are sent)";

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    try {
      await updateWhatsAppConfig({
        enabled,
        sender_number: senderNumber.trim() || null,
        template_name: templateName.trim() || null,
        business_name: businessName.trim() || null,
      });
      await onSaved();
      toast("WhatsApp settings saved.", "success");
    } catch (err) {
      toast(isApiError(err) ? err.message : "Something went wrong", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card className="p-6">
      <form onSubmit={onSubmit} className="flex max-w-xl flex-col gap-5">
        <p className="text-body-sm text-ink-secondary">
          Provider: <span className="font-medium text-ink">{providerLabel}</span>
        </p>
        {/* Enable toggle */}
        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="mt-0.5 size-4 shrink-0 rounded accent-accent-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <span className="flex flex-col">
            <span className="text-body-sm font-medium text-ink">
              Enable WhatsApp for this school
            </span>
            <span className="text-body-sm text-ink-secondary">
              When on, this school is prepared to send photos over WhatsApp once automated
              sending is switched on.
            </span>
          </span>
        </label>

        <Field label="Sender number" htmlFor="wa-sender" hint={sharedHint}>
          <Input
            id="wa-sender"
            inputMode="tel"
            maxLength={32}
            placeholder="15551234567"
            value={senderNumber}
            onChange={(e) => setSenderNumber(e.target.value)}
          />
        </Field>

        <Field label={templateLabel} htmlFor="wa-template" hint={templateHint}>
          <Input
            id="wa-template"
            maxLength={200}
            placeholder={templatePlaceholder}
            value={templateName}
            onChange={(e) => setTemplateName(e.target.value)}
          />
        </Field>

        <Field
          label="Business name"
          htmlFor="wa-business"
          hint="The display name families see. Optional."
        >
          <Input
            id="wa-business"
            maxLength={200}
            value={businessName}
            onChange={(e) => setBusinessName(e.target.value)}
          />
        </Field>

        {/* Honest note: W1 saves settings only — it sends nothing yet. */}
        <p className="rounded-button bg-surface px-3 py-2 text-body-sm text-ink-secondary">
          Saving configuration does not send anything yet — automated sending arrives next.
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

function WhatsAppSettingsInner() {
  const { config, isLoading, error, mutate } = useWhatsAppConfig();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="WhatsApp"
        description="Configure how your school sends photos to families over WhatsApp."
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
          title="Couldn't load WhatsApp settings"
          description="Something went wrong reaching the server."
          action={
            <Button variant="secondary" onClick={() => mutate()}>
              Retry
            </Button>
          }
        />
      ) : (
        // Remount the form when the loaded config changes (post-save revalidate) so its state is
        // re-seeded from props, avoiding a setState-in-effect.
        <WhatsAppForm
          key={config.updated_at}
          config={config}
          onSaved={() => mutate()}
        />
      )}
    </div>
  );
}

export default function WhatsAppSettingsPage() {
  // WhatsApp config is school-admin only (whatsapp:manage). A teacher who deep-links here is
  // redirected home; the backend also 403s.
  return (
    <RoleGate allow={["school_admin"]}>
      <WhatsAppSettingsInner />
    </RoleGate>
  );
}
