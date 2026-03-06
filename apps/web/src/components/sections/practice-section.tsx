"use client";

import { lazy, useMemo } from "react";
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
}: PracticeSectionProps) {
  const tabs = useMemo(
    () => (showReview ? ALL_TABS : ALL_TABS.filter((t) => t.id !== "review")),
    [showReview],
  );

  return (
    <TabbedSection tabs={tabs} defaultTab="quiz" testId="practice-section">
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
