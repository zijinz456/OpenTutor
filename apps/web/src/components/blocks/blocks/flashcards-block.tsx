"use client";

import { PracticeSection } from "@/components/sections/practice-section";
import type { BlockComponentProps } from "@/lib/block-system/registry";

export default function FlashcardsBlock({ courseId, aiActionsEnabled }: BlockComponentProps) {
  return (
    <div role="region" aria-label="Flashcards">
      <PracticeSection
        courseId={courseId}
        aiActionsEnabled={aiActionsEnabled}
        defaultTab="flashcards"
      />
    </div>
  );
}
