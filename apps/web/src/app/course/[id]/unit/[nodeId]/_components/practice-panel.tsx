import { Suspense, lazy } from "react";
import { Button } from "@/components/ui/button";

const PracticeSection = lazy(() =>
  import("@/components/sections/practice-section").then((m) => ({ default: m.PracticeSection })),
);

type TranslateFn = (key: string) => string;
type TranslateFormatFn = (key: string, vars?: Record<string, string | number | null | undefined>) => string;

interface PracticePanelProps {
  courseId: string;
  difficultyLevel: string;
  aiActionsEnabled: boolean;
  generatingFocusedQuiz: boolean;
  onGenerateFocusedQuiz: () => void;
  t: TranslateFn;
  tf: TranslateFormatFn;
}

export function PracticePanel({
  courseId,
  difficultyLevel,
  aiActionsEnabled,
  generatingFocusedQuiz,
  onGenerateFocusedQuiz,
  t,
  tf,
}: PracticePanelProps) {
  return (
    <section className="rounded-2xl bg-card card-shadow overflow-hidden">
      <div className="flex items-center gap-2 px-5 py-3 border-b border-border/60 bg-muted/20">
        <div>
          <h2 className="text-base font-semibold">{t("course.practice")}</h2>
          <p className="text-xs text-muted-foreground mt-0.5">{t("unit.practice.desc")}</p>
        </div>
        <div className="ml-auto">
          <Button
            size="sm"
            variant="outline"
            disabled={!aiActionsEnabled || generatingFocusedQuiz}
            onClick={onGenerateFocusedQuiz}
          >
            {generatingFocusedQuiz
              ? t("unit.generating")
              : tf("unit.generateFocusedQuizWithDifficulty", { level: t(`unit.difficulty.${difficultyLevel}`) })}
          </Button>
        </div>
      </div>
      <div className="min-h-[320px]">
        <Suspense fallback={<div className="p-4 text-sm text-muted-foreground animate-pulse">{t("unit.loading.practice")}</div>}>
          <PracticeSection courseId={courseId} showReview={false} aiActionsEnabled={aiActionsEnabled} defaultTab="quiz" />
        </Suspense>
      </div>
    </section>
  );
}
