"use client";

import * as TabsPrimitive from "@radix-ui/react-tabs";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

/** Underline-style tabs (Radix: roving tabindex, arrow-key nav, aria wired). */
export const Tabs = TabsPrimitive.Root;

export function TabsList({ className, ...props }: ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      className={cn("inline-flex items-center gap-1 border-b border-hairline", className)}
      {...props}
    />
  );
}

export function TabsTrigger({ className, ...props }: ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "-mb-px border-b-2 border-transparent px-3 py-2 text-body font-medium text-ink-secondary transition-colors hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=active]:border-accent-hover data-[state=active]:text-ink",
        className,
      )}
      {...props}
    />
  );
}

export function TabsContent({ className, ...props }: ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content className={cn("mt-6 focus-visible:outline-none", className)} {...props} />
  );
}
