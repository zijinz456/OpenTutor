"use client";

import { lazy, Suspense } from "react";
import type { BlockComponentProps } from "@/lib/block-system/registry";

const GraphView = lazy(() =>
  import("@/components/sections/analytics/graph-view").then((m) => ({ default: m.GraphView })),
);

export default function KnowledgeGraphBlock({ courseId }: BlockComponentProps) {
  return (
    <Suspense fallback={<div className="flex items-center justify-center h-32 text-sm text-muted-foreground">Loading...</div>}>
      <GraphView courseId={courseId} />
    </Suspense>
  );
}
