import { Hammer } from "lucide-react";

import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";

/** Placeholder page for a section landing in a later phase (keeps the shell navigable). */
export function ComingSoon({ title, phase }: { title: string; phase: string }) {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={title} />
      <EmptyState
        icon={<Hammer className="size-8" aria-hidden="true" />}
        title="Coming soon"
        description={`This section lands in ${phase}.`}
      />
    </div>
  );
}
