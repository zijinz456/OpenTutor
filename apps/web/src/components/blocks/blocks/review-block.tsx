"use client";

import { PracticeSection } from "@/components/sections/practice-section";
import type { BlockComponentProps } from "@/lib/block-system/registry";

export default function ReviewBlock({ courseId, aiActionsEnabled }: BlockComponentProps) {
  return <PracticeSection courseId={courseId} showReview aiActionsEnabled={aiActionsEnabled} />;
}
