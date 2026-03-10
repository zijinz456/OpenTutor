import type { ReviewItem } from "@/lib/api";
import type { MasterySummary, ErrorTrendSummary, DifficultyRecommendation } from "./unit-utils";
import { Button } from "@/components/ui/button";

type TranslateFn = (key: string) => string;
type TranslateFormattedFn = (key: string, vars?: Record<string, string | number | null | undefined>) => string;

export function MasteryTimeline({ items, t }: { items: ReviewItem[]; t: TranslateFn }) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("unit.mastery.empty")}</p>;
  }
  return (
    <div className="space-y-2">
      {items.map((item, i) => (
        <div key={`${item.concept_id}-${i}`} className="flex items-center gap-3 rounded-xl bg-muted/30 p-3.5">
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-foreground truncate">{item.concept_label}</p>
            <p className="text-xs text-muted-foreground">
              {t("unit.mastery.stability")}: {item.stability_days}d
              {item.retrievability != null && ` \u00b7 ${t("unit.mastery.retrievability")}: ${Math.round(item.retrievability * 100)}%`}
              {item.last_reviewed && ` \u00b7 ${t("unit.mastery.last")}: ${new Date(item.last_reviewed).toLocaleDateString()}`}
            </p>
          </div>
          <div className="shrink-0">
            <div className="w-20 h-2 bg-muted rounded-full overflow-hidden">
              <div
                className="h-full bg-success rounded-full"
                style={{ width: `${Math.round(item.mastery * 100)}%` }}
              />
            </div>
            <p className="text-[10px] text-muted-foreground text-right mt-0.5">
              {Math.round(item.mastery * 100)}%
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

export function NextActionsSection({
  courseId,
  masterySummary,
  errorTrend,
  difficultyRec,
  quizModeHint,
  aiActionsEnabled,
  generatingFocusedQuiz,
  onGenerateFocusedQuiz,
  onNavigate,
  t,
  tf,
}: {
  courseId: string;
  masterySummary: MasterySummary;
  errorTrend: ErrorTrendSummary;
  difficultyRec: DifficultyRecommendation;
  quizModeHint: string;
  aiActionsEnabled: boolean;
  generatingFocusedQuiz: boolean;
  onGenerateFocusedQuiz: () => void;
  onNavigate: (path: string) => void;
  t: TranslateFn;
  tf: TranslateFormattedFn;
}) {
  return (
    <div className="rounded-2xl bg-card card-shadow p-4">
      <h2 className="text-base font-semibold">{t("unit.nextActions.title")}</h2>
      <p className="text-xs text-muted-foreground mt-0.5">{t("unit.nextActions.desc")}</p>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <div className="rounded-xl bg-muted/30 p-2.5">
          <p className="text-[11px] text-muted-foreground">{t("unit.masterySummary.avgMastery")}</p>
          <p className="text-base font-semibold">{masterySummary.avgMastery}%</p>
        </div>
        <div className="rounded-xl bg-muted/30 p-2.5">
          <p className="text-[11px] text-muted-foreground">{t("unit.masterySummary.avgRetrievability")}</p>
          <p className="text-base font-semibold">{masterySummary.avgRetrievability}%</p>
        </div>
        <div className="rounded-xl bg-muted/30 p-2.5">
          <p className="text-[11px] text-muted-foreground">{t("unit.masterySummary.warning")}</p>
          <p className="text-base font-semibold">{masterySummary.warning}</p>
        </div>
        <div className="rounded-xl bg-muted/30 p-2.5">
          <p className="text-[11px] text-muted-foreground">{t("unit.masterySummary.stale")}</p>
          <p className="text-base font-semibold">{masterySummary.stale}</p>
        </div>
      </div>

      <div className="mt-2 rounded-xl bg-muted/30 p-2.5">
        <div className="flex items-center justify-between gap-2">
          <p className="text-[11px] text-muted-foreground">{t("unit.errorTrend.title")}</p>
          <span
            className={`text-[11px] font-medium ${
              errorTrend.direction === "up"
                ? "text-destructive"
                : errorTrend.direction === "down"
                  ? "text-success"
                  : "text-muted-foreground"
            }`}
          >
            {tf(`unit.errorTrend.${errorTrend.direction}`, { count: Math.abs(errorTrend.delta) })}
          </span>
        </div>
        <p className="text-xs text-muted-foreground mt-1">
          {tf("unit.errorTrend.window", {
            recent: errorTrend.recent7d,
            previous: errorTrend.previous7d,
          })}
        </p>
      </div>

      <div className="mt-2 rounded-xl bg-muted/30 p-2.5">
        <div className="flex items-center justify-between gap-2">
          <p className="text-[11px] text-muted-foreground">{t("unit.difficulty.recommended")}</p>
          <span
            className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ${
              difficultyRec.level === "hard"
                ? "bg-destructive/15 text-destructive"
                : difficultyRec.level === "medium"
                  ? "bg-warning/15 text-warning"
                  : "bg-success/15 text-success"
            }`}
          >
            {t(`unit.difficulty.${difficultyRec.level}`)}
          </span>
        </div>
        <p className="text-xs text-muted-foreground mt-1">{t(difficultyRec.reasonKey)}</p>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() => onNavigate(`/course/${courseId}/review`)}
        >
          {tf("unit.nextActions.review", { count: masterySummary.urgent })}
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => onNavigate(`/course/${courseId}/practice?tab=quiz&mode=${quizModeHint}&difficulty=${difficultyRec.level}`)}
        >
          {t("unit.nextActions.practice")}
        </Button>
        <Button
          size="sm"
          disabled={!aiActionsEnabled || generatingFocusedQuiz}
          onClick={onGenerateFocusedQuiz}
        >
          {generatingFocusedQuiz
            ? t("unit.generating")
            : tf("unit.generateFocusedQuizWithDifficulty", { level: t(`unit.difficulty.${difficultyRec.level}`) })}
        </Button>
      </div>
    </div>
  );
}
