"use client";

import { useSearchParams } from "next/navigation";
import { PracticeSection, type PracticeTab } from "@/components/sections/practice-section";
import { useT } from "@/lib/i18n-context";
import { isLearningMode } from "@/lib/block-system/layout-storage";
import { CoursePageFrame } from "../_components/course-page-frame";
import { useCourseContext } from "../_hooks/course-context";

const PRACTICE_TABS: PracticeTab[] = ["quiz", "flashcards", "mistakes"];

export default function PracticePage() {
  const t = useT();
  const searchParams = useSearchParams();
  const { courseId, aiActionsEnabled } = useCourseContext();

  const requestedTab = searchParams.get("tab");
  const tab: PracticeTab = PRACTICE_TABS.includes(requestedTab as PracticeTab)
    ? (requestedTab as PracticeTab)
    : "quiz";
  const difficultyParam = searchParams.get("difficulty");
  const modeParam = searchParams.get("mode");
  const quizDifficultyHint =
    difficultyParam === "easy" || difficultyParam === "medium" || difficultyParam === "hard"
      ? difficultyParam
      : undefined;
  const quizModeHint = isLearningMode(modeParam) ? modeParam : undefined;

  return (
    <CoursePageFrame title={t("course.practice")}>
      <PracticeSection
        courseId={courseId}
        showMistakes
        aiActionsEnabled={aiActionsEnabled}
        defaultTab={tab}
        quizDifficultyHint={quizDifficultyHint}
        quizModeHint={quizModeHint}
      />
    </CoursePageFrame>
  );
}
