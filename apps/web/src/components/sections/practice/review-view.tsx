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
  type ConfusionPair,
  type WrongAnswer,
} from "@/lib/api";
import { AiFeatureBlocked } from "@/components/shared/ai-feature-blocked";
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

  const [confusionPairs, setConfusionPairs] = useState<ConfusionPair[]>([]);

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
      toast.success("Marked as mastered");
    } catch (error) {
      toast.error((error as Error).message || "Failed to mark as mastered");
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
      toast.error((error as Error).message || "Failed to generate review");
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
      toast.error((error as Error).message || "Failed to derive question");
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
      toast.error((error as Error).message || "Failed to submit diagnostic answer");
      setDiagnosticDrafts((prev) => ({
        ...prev,
        [wrongAnswerId]: { ...draft, pending: false },
      }));
    }
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center" data-testid="review-panel" role="status" aria-live="polite">
        <span className="text-sm animate-pulse text-muted-foreground">Loading review...</span>
      </div>
    );
  }

  if (wrongAnswers.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 text-center" data-testid="review-panel">
        <div>
          <h3 className="text-sm font-medium mb-1">{t("course.review")}</h3>
          <p className="text-xs text-muted-foreground max-w-xs">
            No unmastered wrong answers
          </p>
        </div>
      </div>
    );
  }

  return (
    <div role="region" aria-label="Wrong answer review" className="flex-1 flex flex-col overflow-hidden" data-testid="review-panel">
      <div className="px-3 py-2 border-b border-border/60 flex items-center justify-between text-xs text-muted-foreground" aria-live="polite">
        <span>{wrongAnswers.length} mistakes ready for review</span>
        <Button size="sm" onClick={() => void handleGenerateReview()} disabled={!aiActionsEnabled || generating}>
          {generating ? <span className="mr-1 animate-pulse">...</span> : null}
          Generate Review
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin p-4 space-y-4">
        {!aiActionsEnabled ? <AiFeatureBlocked compact /> : null}
        {stats ? (
          <div className="rounded-2xl card-shadow bg-card p-4 space-y-3" data-testid="review-stats">
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline">Total: {stats.total}</Badge>
              <Badge variant="outline">Unmastered: {stats.unmastered}</Badge>
              <Badge variant="outline">Mastered: {stats.mastered}</Badge>
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

        {confusionPairs.length > 0 ? (
          <div className="space-y-3" data-testid="confusion-pairs">
            <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              Confused Concepts
            </h4>
            {confusionPairs.slice(0, 5).map((pair) => (
              <div
                key={`${pair.concept_a}-${pair.concept_b}`}
                className="rounded-2xl border border-warning/30 bg-warning-muted/10 p-3.5"
              >
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <p className="text-xs font-semibold text-foreground">{pair.concept_a}</p>
                    {pair.description_a ? (
                      <p className="text-[11px] text-muted-foreground leading-relaxed">{pair.description_a}</p>
                    ) : null}
                  </div>
                  <div className="space-y-1">
                    <p className="text-xs font-semibold text-foreground">{pair.concept_b}</p>
                    {pair.description_b ? (
                      <p className="text-[11px] text-muted-foreground leading-relaxed">{pair.description_b}</p>
                    ) : null}
                  </div>
                </div>
                <p className="text-[10px] text-muted-foreground mt-2">
                  Confused {pair.weight}× — review both concepts side by side
                </p>
              </div>
            ))}
          </div>
        ) : null}

        {wrongAnswers.map((item, index) => {
          const draft = diagnosticDrafts[item.id];
          const optionKeys = Object.keys(draft?.options ?? {}).sort();

          return (
            <div key={item.id} className="rounded-2xl card-shadow bg-card p-4 space-y-2" data-testid={`wrong-answer-${item.id}`}>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-medium">
                    {index + 1}. {item.question ?? "Untitled question"}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Badge variant="outline">{item.question_type ?? "unknown"}</Badge>
                    {item.error_category ? <Badge variant="secondary">{item.error_category}</Badge> : null}
                    {item.diagnosis ? (
                      <Badge variant="secondary">{item.diagnosis.replaceAll("_", " ")}</Badge>
                    ) : null}
                  </div>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label="Mark as mastered"
                    onClick={() => void handleMarkMastered(item)}
                    disabled={markingId === item.id || !item.correct_answer}
                  >
                    {markingId === item.id ? "..." : "✓"}
                  </Button>
                  <Button
                    data-testid={`derive-${item.id}`}
                    size="sm"
                    variant="outline"
                    aria-label="Derive diagnostic question"
                    onClick={() => void handleDerive(item.id)}
                    disabled={!aiActionsEnabled || derivingId === item.id}
                  >
                    {derivingId === item.id ? "..." : "Derive"}
                  </Button>
                </div>
              </div>

              {draft ? (
                <div className="rounded-xl bg-muted/30 p-3.5 space-y-2" data-testid={`diagnostic-${item.id}`}>
                  <p className="text-sm font-medium">{draft.question}</p>
                  {optionKeys.map((key) => (
                    <button
                      key={key}
                      type="button"
                      data-testid={`diagnostic-${item.id}-${key}`}
                      className="w-full rounded-xl border px-3.5 py-2.5 text-left text-sm hover:border-primary/50"
                      onClick={() => void handleDiagnosticAnswer(item.id, key)}
                      disabled={!aiActionsEnabled || draft.pending}
                    >
                      <span className="mr-2 font-medium">{key}.</span>
                      {draft.options?.[key]}
                    </button>
                  ))}
                  {draft.diagnosis ? (
                    <p className="text-xs text-muted-foreground" data-testid={`diagnosis-${item.id}`}>
                      {draft.diagnosis.replaceAll("_", " ")}
                    </p>
                  ) : null}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
