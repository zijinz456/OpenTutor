"use client";

import { AnalyticsSection } from "@/components/sections/analytics-section";
import type { BlockComponentProps } from "@/lib/block-system/registry";

export default function KnowledgeGraphBlock({ courseId }: BlockComponentProps) {
  return (
    <div role="region" aria-label="Knowledge graph">
      <AnalyticsSection courseId={courseId} defaultTab="graph" />
    </div>
  );
}
