"use client";

import { useT } from "@/lib/i18n-context";
import { Badge } from "@/components/ui/badge";
import type { AnswerResult } from "@/lib/api";

interface QuizResultProps {
  result: AnswerResult;
}

export function QuizResult({ result }: QuizResultProps) {
  const t = useT();
  const badgeText = result.is_correct
    ? t("quiz.correct")
    : result.correct_answer?.toUpperCase() || t("quiz.answerRecorded");
  const fallbackCopy = result.is_correct
    ? t("quiz.answerRecorded")
    : result.correct_answer
      ? `${t("quiz.correctAnswerLabel")} ${result.correct_answer.toUpperCase()}`
      : t("quiz.feedbackUnavailable");

  return (
    <>
      <div className="space-y-1.5 pt-1" aria-live="assertive">
        <Badge variant={result.is_correct ? "default" : "destructive"}>
          {badgeText}
        </Badge>
        <p className="text-xs text-muted-foreground leading-relaxed">
          {result.explanation ? `${t("quiz.explanation")} ${result.explanation}` : fallbackCopy}
        </p>
      </div>

      {result.prerequisite_gaps && result.prerequisite_gaps.length > 0 ? (
        <div className="rounded-2xl border border-warning/30 bg-warning-muted/20 p-3.5 space-y-2">
          <p className="text-xs font-semibold text-warning">
            {t("quiz.prerequisiteGaps") !== "quiz.prerequisiteGaps"
              ? t("quiz.prerequisiteGaps")
              : "Prerequisite gaps detected"}
          </p>
          <div className="space-y-1.5">
            {result.prerequisite_gaps.map((gap) => (
              <div key={gap.concept_id} className="flex items-center justify-between text-xs">
                <span className="text-foreground">{gap.concept}</span>
                <div className="flex items-center gap-2">
                  <div className="w-16 h-1.5 bg-muted rounded-full overflow-hidden">
                    <div
                      className="h-full bg-warning rounded-full"
                      style={{ width: `${Math.round(gap.mastery * 100)}%` }}
                    />
                  </div>
                  <span className="text-muted-foreground w-8 text-right">
                    {Math.round(gap.mastery * 100)}%
                  </span>
                </div>
              </div>
            ))}
          </div>
          <p className="text-[10px] text-muted-foreground">
            {t("quiz.prerequisiteHint") !== "quiz.prerequisiteHint"
              ? t("quiz.prerequisiteHint")
              : "Strengthen these foundational concepts to improve your understanding."}
          </p>
        </div>
      ) : null}
    </>
  );
}
