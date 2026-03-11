"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useT } from "@/lib/i18n-context";
import { MarkdownRenderer } from "@/components/shared/markdown-renderer";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  diagnoseWrongAnswer,
  deriveQuestion,
  getConfusionPairs,
  getWrongAnswerReview,
  getWrongAnswerStats,
  listWrongAnswers,
  retryWrongAnswer,
  submitAnswer,
  type WrongAnswer,
} from "@/lib/api";
import { AiFeatureBlocked } from "@/components/shared/ai-feature-blocked";
import { SkeletonText } from "@/components/ui/skeleton";
import { WrongAnswerCard } from "./wrong-answer-card";
import { ConfusionPairs } from "./confusion-pairs";
import { toast } from "sonner";

interface ReviewViewProps {
  courseId: string;
  aiActionsEnabled?: boolean;
}

export function ReviewView({
  courseId,
  aiActionsEnabled = true,
}: ReviewViewProps) {
  const t = useT();
  const [wrongAnswers, setWrongAnswers] = useState<WrongAnswer[]>([]);
  const [reviewMarkdown, setReviewMarkdown] = useState("");
  const [stats, setStats] = useState<{
    total: number;
    mastered: number;
    unmastered: number;
    by_category: Record<string, number>;
    by_diagnosis: Record<string, number>;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [markingId, setMarkingId] = useState<string | null>(null);
  const [derivingId, setDerivingId] = useState<string | null>(null);
  const [diagnosticDrafts, setDiagnosticDrafts] = useState<
    Record<
      string,
      {
        problemId: string;
        question: string;
        options: Record<string, string> | null;
        selectedAnswer?: string;
        diagnosis?: string;
        pending?: boolean;
      }
    >
  >({});

  const [confusionPairs, setConfusionPairs] = useState<import("@/lib/api").ConfusionPair[]>([]);

  const loadWrongAnswers = useCallback(async () => {
    try {
      const [items, summary, confusion] = await Promise.all([
        listWrongAnswers(courseId, { mastered: false }),
        getWrongAnswerStats(courseId),
        getConfusionPairs(courseId).catch(() => ({ pairs: [], count: 0 })),
      ]);
      setWrongAnswers(items);
      setStats(summary);
      setConfusionPairs(confusion.pairs);
    } catch {
      setWrongAnswers([]);
      setStats(null);
    } finally {
      setLoading(false);
    }
  }, [courseId]);

  useEffect(() => {
    void loadWrongAnswers();
  }, [loadWrongAnswers]);

  const diagnosisSummary = useMemo(
    () => Object.entries(stats?.by_diagnosis ?? {}),
    [stats?.by_diagnosis],
  );

  const handleMarkMastered = async (item: WrongAnswer) => {
    if (!item.correct_answer) return;
    setMarkingId(item.id);
    try {
      await retryWrongAnswer(item.id, item.correct_answer);
      await loadWrongAnswers();
      toast.success(t("review.markedMastered"));
    } catch (error) {
      toast.error((error as Error).message || t("review.markFailed"));
    } finally {
      setMarkingId(null);
    }
  };

  const handleGenerateReview = async () => {
    setGenerating(true);
    try {
      const result = await getWrongAnswerReview(courseId);
      setReviewMarkdown(result.review);
    } catch (error) {
      toast.error((error as Error).message || t("review.generateFailed"));
    } finally {
      setGenerating(false);
    }
  };

  const handleDerive = async (wrongAnswerId: string) => {
    setDerivingId(wrongAnswerId);
    try {
      const result = await deriveQuestion(wrongAnswerId);
      setDiagnosticDrafts((prev) => ({
        ...prev,
        [wrongAnswerId]: {
          problemId: result.problem_id,
          question: result.question,
          options: result.options,
        },
      }));
    } catch (error) {
      toast.error((error as Error).message || t("review.deriveFailed"));
    } finally {
      setDerivingId(null);
    }
  };

  const handleDiagnosticAnswer = async (wrongAnswerId: string, answer: string) => {
    const draft = diagnosticDrafts[wrongAnswerId];
    if (!draft || draft.pending) return;

    setDiagnosticDrafts((prev) => ({
      ...prev,
      [wrongAnswerId]: { ...draft, selectedAnswer: answer, pending: true },
    }));

    try {
      await submitAnswer(draft.problemId, answer);
      const diagnosis = await diagnoseWrongAnswer(wrongAnswerId);
      setDiagnosticDrafts((prev) => ({
        ...prev,
        [wrongAnswerId]: {
          ...prev[wrongAnswerId],
          selectedAnswer: answer,
          diagnosis: diagnosis.diagnosis,
          pending: false,
        },
      }));
      await loadWrongAnswers();
    } catch (error) {
      toast.error((error as Error).message || t("review.diagnosticFailed"));
      setDiagnosticDrafts((prev) => ({
        ...prev,
        [wrongAnswerId]: { ...draft, pending: false },
      }));
    }
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center p-8" data-testid="review-panel" role="status" aria-live="polite">
        <SkeletonText lines={3} className="w-full max-w-md" />
      </div>
    );
  }

  if (wrongAnswers.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 text-center" data-testid="review-panel">
        <div>
          <h3 className="text-sm font-medium mb-1">{t("course.review")}</h3>
          <p className="text-xs text-muted-foreground max-w-xs">
            {t("review.noUnmastered")}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div role="region" aria-label={t("review.ariaLabel")} className="flex-1 flex flex-col overflow-hidden" data-testid="review-panel">
      <div className="px-3 py-2 border-b border-border/60 flex items-center justify-between text-xs text-muted-foreground" aria-live="polite">
        <span>{t("review.mistakesReady").replace("{count}", String(wrongAnswers.length))}</span>
        <Button size="sm" onClick={() => void handleGenerateReview()} disabled={!aiActionsEnabled || generating}>
          {generating ? <span className="mr-1 animate-pulse">...</span> : null}
          {t("review.generateReview")}
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin p-4 space-y-4">
        {!aiActionsEnabled ? <AiFeatureBlocked compact /> : null}
        {stats ? (
          <div className="rounded-2xl card-shadow bg-card p-4 space-y-3" data-testid="review-stats">
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline">{t("review.statsTotal").replace("{count}", String(stats.total))}</Badge>
              <Badge variant="outline">{t("review.statsUnmastered").replace("{count}", String(stats.unmastered))}</Badge>
              <Badge variant="outline">{t("review.statsMastered").replace("{count}", String(stats.mastered))}</Badge>
            </div>
            {diagnosisSummary.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {diagnosisSummary.map(([label, count]) => (
                  <Badge key={label} variant="secondary">
                    {label.replaceAll("_", " ")}: {count}
                  </Badge>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}

        {reviewMarkdown ? (
          <div className="rounded-2xl bg-muted/30 p-4 prose prose-sm max-w-none" data-testid="review-markdown">
            <MarkdownRenderer content={reviewMarkdown} />
          </div>
        ) : null}

        <ConfusionPairs pairs={confusionPairs} />

        {wrongAnswers.map((item, index) => (
          <WrongAnswerCard
            key={item.id}
            item={item}
            index={index}
            draft={diagnosticDrafts[item.id]}
            markingId={markingId}
            derivingId={derivingId}
            aiActionsEnabled={aiActionsEnabled}
            onMarkMastered={handleMarkMastered}
            onDerive={handleDerive}
            onDiagnosticAnswer={handleDiagnosticAnswer}
          />
        ))}
      </div>
    </div>
  );
}
