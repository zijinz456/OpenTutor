"use client";

import { lazy, Suspense } from "react";
import type { BlockComponentProps } from "@/lib/block-system/registry";

const ProgressView = lazy(() =>
  import("@/components/sections/analytics/progress-view").then((m) => ({ default: m.ProgressView })),
);

export default function ProgressBlock({ courseId }: BlockComponentProps) {
  return (
    <Suspense fallback={<div className="flex items-center justify-center h-32 text-sm text-muted-foreground">Loading...</div>}>
      <ProgressView courseId={courseId} />
    </Suspense>
  );
}
