"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useT } from "@/lib/i18n-context";
import { MarkdownRenderer } from "@/components/shared/markdown-renderer";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  diagnoseWrongAnswer,
  deriveQuestion,
  getWrongAnswerReview,
  getWrongAnswerStats,
  listWrongAnswers,
  retryWrongAnswer,
  submitAnswer,
  type WrongAnswer,
} from "@/lib/api";
import { toast } from "sonner";

interface ReviewViewProps {
  courseId: string;
}

export function ReviewView({ courseId }: ReviewViewProps) {
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

  const loadWrongAnswers = useCallback(async () => {
    try {
      const [items, summary] = await Promise.all([
        listWrongAnswers(courseId, { mastered: false }),
        getWrongAnswerStats(courseId),
      ]);
      setWrongAnswers(items);
      setStats(summary);
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
      <div className="flex-1 flex items-center justify-center" data-testid="review-panel">
        <span className="text-sm animate-pulse text-muted-foreground">...</span>
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
    <div className="flex-1 flex flex-col overflow-hidden" data-testid="review-panel">
      <div className="px-3 py-2 border-b flex items-center justify-between text-xs text-muted-foreground">
        <span>{wrongAnswers.length} mistakes ready for review</span>
        <Button size="sm" onClick={() => void handleGenerateReview()} disabled={generating}>
          {generating ? <span className="mr-1 animate-pulse">...</span> : null}
          Generate Review
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {stats ? (
          <div className="rounded-lg border bg-card p-4 space-y-3" data-testid="review-stats">
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
          <div className="rounded-lg border bg-muted/30 p-4 prose prose-sm max-w-none" data-testid="review-markdown">
            <MarkdownRenderer content={reviewMarkdown} />
          </div>
        ) : null}

        {wrongAnswers.map((item, index) => {
          const draft = diagnosticDrafts[item.id];
          const optionKeys = Object.keys(draft?.options ?? {}).sort();

          return (
            <div key={item.id} className="rounded-lg border bg-card p-4 space-y-2" data-testid={`wrong-answer-${item.id}`}>
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
                    onClick={() => void handleMarkMastered(item)}
                    disabled={markingId === item.id || !item.correct_answer}
                  >
                    {markingId === item.id ? "..." : "✓"}
                  </Button>
                  <Button
                    data-testid={`derive-${item.id}`}
                    size="sm"
                    variant="outline"
                    onClick={() => void handleDerive(item.id)}
                    disabled={derivingId === item.id}
                  >
                    {derivingId === item.id ? "..." : "Derive"}
                  </Button>
                </div>
              </div>

              {draft ? (
                <div className="rounded-md border bg-muted/20 p-3 space-y-2" data-testid={`diagnostic-${item.id}`}>
                  <p className="text-sm font-medium">{draft.question}</p>
                  {optionKeys.map((key) => (
                    <button
                      key={key}
                      type="button"
                      data-testid={`diagnostic-${item.id}-${key}`}
                      className="w-full rounded-md border px-3 py-2 text-left text-sm hover:border-primary/50"
                      onClick={() => void handleDiagnosticAnswer(item.id, key)}
                      disabled={draft.pending}
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
