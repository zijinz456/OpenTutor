"use client";

import { Suspense, lazy } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useT } from "@/lib/i18n-context";

const QuizView = lazy(() =>
  import("./practice/quiz-view").then((m) => ({ default: m.QuizView })),
);
const FlashcardView = lazy(() =>
  import("./practice/flashcard-view").then((m) => ({ default: m.FlashcardView })),
);
const ReviewView = lazy(() =>
  import("./practice/review-view").then((m) => ({ default: m.ReviewView })),
);

interface PracticeSectionProps {
  courseId: string;
}

function SubViewSkeleton() {
  return (
    <div className="flex-1 flex items-center justify-center p-8">
      <div className="h-4 w-32 bg-muted animate-pulse rounded" />
    </div>
  );
}

/**
 * Practice section -- unified Quiz + Flashcards + Review.
 *
 * Uses internal sub-tabs for switching between the three practice modes.
 * Each sub-view is lazily loaded to reduce initial bundle size.
 */
export function PracticeSection({ courseId }: PracticeSectionProps) {
  const t = useT();

  return (
    <div className="flex-1 flex flex-col overflow-hidden" data-testid="practice-section">
      <Tabs defaultValue="quiz" className="flex-1 flex flex-col overflow-hidden">
        <div className="px-3 py-1.5 border-b shrink-0">
          <TabsList className="h-7">
            <TabsTrigger value="quiz" className="text-xs px-2.5 h-6">
              {t("quiz.title")}
            </TabsTrigger>
            <TabsTrigger value="flashcards" className="text-xs px-2.5 h-6">
              {t("flashcard.title")}
            </TabsTrigger>
            <TabsTrigger value="review" className="text-xs px-2.5 h-6">
              {t("course.review")}
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="quiz" className="flex-1 flex flex-col overflow-hidden mt-0">
          <Suspense fallback={<SubViewSkeleton />}>
            <QuizView courseId={courseId} />
          </Suspense>
        </TabsContent>

        <TabsContent value="flashcards" className="flex-1 flex flex-col overflow-hidden mt-0">
          <Suspense fallback={<SubViewSkeleton />}>
            <FlashcardView courseId={courseId} />
          </Suspense>
        </TabsContent>

        <TabsContent value="review" className="flex-1 flex flex-col overflow-hidden mt-0">
          <Suspense fallback={<SubViewSkeleton />}>
            <ReviewView courseId={courseId} />
          </Suspense>
        </TabsContent>
      </Tabs>
    </div>
  );
}
