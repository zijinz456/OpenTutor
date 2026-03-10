"use client";

import { AnalyticsSection } from "@/components/sections/analytics-section";
import type { BlockComponentProps } from "@/lib/block-system/registry";

export default function ProgressBlock({ courseId }: BlockComponentProps) {
  return (
    <div role="region" aria-label="Progress">
      <AnalyticsSection courseId={courseId} defaultTab="progress" />
    </div>
  );
}
