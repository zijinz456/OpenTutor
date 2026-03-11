"use client";

import { lazy, Suspense } from "react";
import type { BlockComponentProps } from "@/lib/block-system/registry";

const MisconceptionView = lazy(() =>
  import("@/components/sections/analytics/misconception-view").then((m) => ({ default: m.MisconceptionView })),
);

export default function WrongAnswersBlock({ courseId }: BlockComponentProps) {
  return (
    <Suspense fallback={<div className="flex items-center justify-center h-32 text-sm text-muted-foreground">Loading...</div>}>
      <MisconceptionView courseId={courseId} />
    </Suspense>
  );
}
