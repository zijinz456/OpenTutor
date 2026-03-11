"use client";

import { lazy, Suspense } from "react";
import type { BlockComponentProps } from "@/lib/block-system/registry";
import { BlockSkeleton } from "@/components/shared/block-skeleton";

const GraphView = lazy(() =>
  import("@/components/sections/analytics/graph-view").then((m) => ({ default: m.GraphView })),
);

export default function KnowledgeGraphBlock({ courseId }: BlockComponentProps) {
  return (
    <Suspense fallback={<BlockSkeleton />}>
      <GraphView courseId={courseId} />
    </Suspense>
  );
}
