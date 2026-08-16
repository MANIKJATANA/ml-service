import type { Metadata } from "next";

import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";

export const metadata: Metadata = {
  title: "How photo matching works",
};

/**
 * BP21 (R3-S5-03): a plain-language explainer of face matching — for students (who are asked
 * "Is this you?" about a system nobody named) and staff (who correct confidence percentages
 * nobody defined). Static content; no data, no role-specific copy.
 */
export default function HowMatchingWorksPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="How photo matching works"
        description="A quick guide to how your school's event photos reach the students in them."
      />

      <Card className="flex flex-col gap-6 p-6 text-body text-ink">
        <section className="flex flex-col gap-2">
          <h2 className="text-headline text-ink">What it does</h2>
          <p className="text-ink-secondary">
            After an event, staff upload the photos. The app looks at the faces in each photo and
            works out which students are in it — so every student can find the photos they appear
            in, without anyone tagging them by hand.
          </p>
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-headline text-ink">How it recognizes a face</h2>
          <p className="text-ink-secondary">
            When a student is added, the school saves one clear reference photo of them. When event
            photos are matched, the app compares each face it finds against those reference photos
            and lists the students it recognizes. It only ever compares within your own school.
          </p>
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-headline text-ink">What the confidence percentage means</h2>
          <p className="text-ink-secondary">
            Each match comes with a confidence score — how sure the app is that the face belongs to
            that student. Higher is surer. It&apos;s a helpful signal, not a guarantee: a low score,
            or occasionally a confident-but-wrong match, can happen (similar-looking people, a
            blurry or side-on face). Treat a low score as &ldquo;worth a second look&rdquo;.
          </p>
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-headline text-ink">If a match is wrong</h2>
          <p className="text-ink-secondary">
            Nobody has to live with a mistake. A student can flag a photo that isn&apos;t them with
            &ldquo;This isn&apos;t me&rdquo; — it&apos;s hidden from them straight away. Staff can
            confirm, remove, or add a student to a photo from the event&apos;s review view. Fixing a
            match never changes the photo itself, only who&apos;s listed in it.
          </p>
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-headline text-ink">Who can see what</h2>
          <p className="text-ink-secondary">
            A student only sees the photos they appear in, and those are private to them and their
            school&apos;s staff. Other students never see a photo unless they&apos;re in it too.
          </p>
        </section>
      </Card>
    </div>
  );
}
