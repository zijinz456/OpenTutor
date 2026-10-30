"use client";

import { lazy, useCallback, useMemo } from "react";
import { useT } from "@/lib/i18n-context";
import { useWorkspaceStore } from "@/store/workspace";
import { TabbedSection, type TabDef } from "./tabbed-section";

const QuizView = lazy(() =>
  import("./practice/quiz-view").then((m) => ({ default: m.QuizView })),
);
const FlashcardView = lazy(() =>
  import("./practice/flashcard-view").then((m) => ({ default: m.FlashcardView })),
);
const MistakesView = lazy(() =>
  import("./practice/mistakes-view").then((m) => ({ default: m.MistakesView })),
);
interface PracticeSectionProps {
  courseId: string;
  /** Show the wrong-answer ("mistakes") tab. */
  showMistakes?: boolean;
  aiActionsEnabled?: boolean;
  defaultTab?: PracticeTab;
  quizDifficultyHint?: "easy" | "medium" | "hard";
  quizModeHint?: "course_following" | "self_paced" | "exam_prep" | "maintenance";
}

export type PracticeTab = "quiz" | "flashcards" | "mistakes";

export function PracticeSection({
  courseId,
  showMistakes = true,
  aiActionsEnabled = true,
  defaultTab = "quiz",
  quizDifficultyHint,
  quizModeHint,
}: PracticeSectionProps) {
  const t = useT();
  const allTabs: TabDef<PracticeTab>[] = useMemo(
    () => [
      { id: "quiz", label: t("course.quiz"), testId: "right-tab-quiz" },
      { id: "flashcards", label: t("course.cards"), testId: "right-tab-cards" },
      { id: "mistakes", label: t("course.mistakes"), testId: "right-tab-mistakes" },
    ],
    [t],
  );
  const tabs = useMemo(
    () => (showMistakes ? allTabs : allTabs.filter((tab) => tab.id !== "mistakes")),
    [showMistakes, allTabs],
  );

  const practiceActiveTab = useWorkspaceStore((s) => s.practiceActiveTab) as PracticeTab | null;
  const clearPracticeTab = useCallback(() => {
    useWorkspaceStore.getState().setPracticeTab(null);
  }, []);

  return (
    <div role="region" aria-label="Practice">
    <TabbedSection
      tabs={tabs}
      defaultTab={tabs.some((t) => t.id === defaultTab) ? defaultTab : "quiz"}
      testId="practice-section"
      externalTab={practiceActiveTab}
      onExternalTabConsumed={clearPracticeTab}
    >
      {(activeTab) => (
        <>
          {activeTab === "quiz" ? (
            <QuizView
              courseId={courseId}
              aiActionsEnabled={aiActionsEnabled}
              modeHint={quizModeHint}
              difficultyHint={quizDifficultyHint}
            />
          ) : null}
          {activeTab === "flashcards" ? <FlashcardView courseId={courseId} aiActionsEnabled={aiActionsEnabled} /> : null}
          {activeTab === "mistakes" && showMistakes ? <MistakesView courseId={courseId} aiActionsEnabled={aiActionsEnabled} /> : null}
        </>
      )}
    </TabbedSection>
    </div>
  );
}
