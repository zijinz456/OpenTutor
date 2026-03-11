"use client";

import { lazy, Suspense } from "react";
import type { BlockComponentProps } from "@/lib/block-system/registry";
import { BlockSkeleton } from "@/components/shared/block-skeleton";

const MisconceptionView = lazy(() =>
  import("@/components/sections/analytics/misconception-view").then((m) => ({ default: m.MisconceptionView })),
);

export default function WrongAnswersBlock({ courseId }: BlockComponentProps) {
  return (
    <Suspense fallback={<BlockSkeleton />}>
      <MisconceptionView courseId={courseId} />
    </Suspense>
  );
}
