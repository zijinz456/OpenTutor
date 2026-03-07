"use client";

import { PracticeSection } from "@/components/sections/practice-section";
import type { BlockComponentProps } from "@/lib/block-system/registry";

export default function QuizBlock({ courseId, aiActionsEnabled }: BlockComponentProps) {
  return <PracticeSection courseId={courseId} aiActionsEnabled={aiActionsEnabled} />;
}
