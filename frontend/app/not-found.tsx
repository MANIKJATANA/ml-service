import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { FullPageMessage } from "@/components/ui/full-page-message";

export default function NotFound() {
  return (
    <FullPageMessage
      title="Page not found"
      description="The page you're looking for doesn't exist or has moved."
      action={
        <Link href="/" className={buttonVariants({ variant: "secondary" })}>
          Go home
        </Link>
      }
    />
  );
}
