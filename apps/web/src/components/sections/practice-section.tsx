"use client";

import { lazy, useCallback, useMemo } from "react";
import { useWorkspaceStore } from "@/store/workspace";
import { TabbedSection, type TabDef } from "./tabbed-section";

const QuizView = lazy(() =>
  import("./practice/quiz-view").then((m) => ({ default: m.QuizView })),
);
const FlashcardView = lazy(() =>
  import("./practice/flashcard-view").then((m) => ({ default: m.FlashcardView })),
);
const ReviewView = lazy(() =>
  import("./practice/review-view").then((m) => ({ default: m.ReviewView })),
);
const PodcastView = lazy(() =>
  import("./practice/podcast-view").then((m) => ({ default: m.PodcastView })),
);

interface PracticeSectionProps {
  courseId: string;
  showReview?: boolean;
  aiActionsEnabled?: boolean;
  defaultTab?: PracticeTab;
}

type PracticeTab = "quiz" | "flashcards" | "review" | "podcast";

const ALL_TABS: TabDef<PracticeTab>[] = [
  { id: "quiz", label: "Quiz", testId: "right-tab-quiz" },
  { id: "flashcards", label: "Cards", testId: "right-tab-cards" },
  { id: "review", label: "Review", testId: "right-tab-review" },
  { id: "podcast", label: "Podcast", testId: "right-tab-podcast" },
];

export function PracticeSection({
  courseId,
  showReview = true,
  aiActionsEnabled = true,
  defaultTab = "quiz",
}: PracticeSectionProps) {
  const tabs = useMemo(
    () => (showReview ? ALL_TABS : ALL_TABS.filter((t) => t.id !== "review")),
    [showReview],
  );

  const practiceActiveTab = useWorkspaceStore((s) => s.practiceActiveTab) as PracticeTab | null;
  const clearPracticeTab = useCallback(() => {
    useWorkspaceStore.getState().setPracticeTab(null);
  }, []);

  return (
    <TabbedSection
      tabs={tabs}
      defaultTab={tabs.some((t) => t.id === defaultTab) ? defaultTab : "quiz"}
      testId="practice-section"
      externalTab={practiceActiveTab}
      onExternalTabConsumed={clearPracticeTab}
    >
      {(activeTab) => (
        <>
          {activeTab === "quiz" ? <QuizView courseId={courseId} aiActionsEnabled={aiActionsEnabled} /> : null}
          {activeTab === "flashcards" ? <FlashcardView courseId={courseId} aiActionsEnabled={aiActionsEnabled} /> : null}
          {activeTab === "review" && showReview ? <ReviewView courseId={courseId} aiActionsEnabled={aiActionsEnabled} /> : null}
          {activeTab === "podcast" ? <PodcastView courseId={courseId} aiActionsEnabled={aiActionsEnabled} /> : null}
        </>
      )}
    </TabbedSection>
  );
}
