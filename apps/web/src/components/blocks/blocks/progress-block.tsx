"use client";

import { lazy, Suspense } from "react";
import type { BlockComponentProps } from "@/lib/block-system/registry";
import { BlockSkeleton } from "@/components/shared/block-skeleton";

const ProgressView = lazy(() =>
  import("@/components/sections/analytics/progress-view").then((m) => ({ default: m.ProgressView })),
);

export default function ProgressBlock({ courseId }: BlockComponentProps) {
  return (
    <Suspense fallback={<BlockSkeleton />}>
      <ProgressView courseId={courseId} />
    </Suspense>
  );
}
