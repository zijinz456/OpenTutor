"use client";

import { PracticeSection } from "@/components/sections/practice-section";
import type { BlockComponentProps } from "@/lib/block-system/registry";

export default function QuizBlock({ courseId, aiActionsEnabled }: BlockComponentProps) {
  return (
    <div role="region" aria-label="Quiz">
      <PracticeSection
        courseId={courseId}
        aiActionsEnabled={aiActionsEnabled}
        defaultTab="quiz"
      />
    </div>
  );
}
