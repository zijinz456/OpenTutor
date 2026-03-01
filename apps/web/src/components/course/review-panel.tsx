"use client";

import { useCallback, useEffect, useState } from "react";
import { MarkdownRenderer } from "@/components/course/markdown-renderer";
import { Loader2, RefreshCcw, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  diagnoseWrongAnswer,
  deriveQuestion,
  getWrongAnswerReview,
  getWrongAnswerStats,
  listWrongAnswers,
  submitAnswer,
  type WrongAnswer,
} from "@/lib/api";
import { toast } from "sonner";

interface ReviewPanelProps {
  courseId: string;
}

export function ReviewPanel({ courseId }: ReviewPanelProps) {
  const [wrongAnswers, setWrongAnswers] = useState<WrongAnswer[]>([]);
  const [reviewMarkdown, setReviewMarkdown] = useState<string>("");
  const [stats, setStats] = useState<{
    total: number;
    mastered: number;
    unmastered: number;
    by_category: Record<string, number>;
    by_diagnosis: Record<string, number>;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [derivingId, setDerivingId] = useState<string | null>(null);
  const [diagnosticDrafts, setDiagnosticDrafts] = useState<
    Record<
      string,
      {
        problemId: string;
        question: string;
        options: Record<string, string> | null;
        correctAnswer: string | null;
        explanation: string | null;
        selectedAnswer?: string;
        diagnosis?: string;
        pending?: boolean;
      }
    >
  >({});

  const loadWrongAnswers = useCallback(async () => {
    setLoading(true);
    try {
      const items = await listWrongAnswers(courseId, { mastered: false });
      setWrongAnswers(items);
      setStats(await getWrongAnswerStats(courseId));
    } catch {
      setWrongAnswers([]);
      setStats(null);
    } finally {
      setLoading(false);
    }
  }, [courseId]);

  useEffect(() => {
    loadWrongAnswers();
  }, [loadWrongAnswers]);

  const handleGenerateReview = async () => {
    setGenerating(true);
    try {
      const result = await getWrongAnswerReview(courseId);
      setReviewMarkdown(result.review);
      toast.success(`Generated review for ${result.wrong_answer_count} wrong answers`);
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
          correctAnswer: result.correct_answer,
          explanation: result.explanation,
        },
      }));
      toast.success(`Derived question: ${result.question.slice(0, 60)}`);
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
          pending: false,
          diagnosis: diagnosis.diagnosis,
        },
      }));
      await loadWrongAnswers();
      toast.success(diagnosis.diagnosis ? `Diagnosis: ${diagnosis.diagnosis.replaceAll("_", " ")}` : "Diagnostic answer submitted");
    } catch (error) {
      setDiagnosticDrafts((prev) => ({
        ...prev,
        [wrongAnswerId]: { ...draft, selectedAnswer: answer, pending: false },
      }));
      toast.error((error as Error).message || "Failed to submit diagnostic answer");
    }
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (wrongAnswers.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-4 text-center">
        <div>
          <p className="text-muted-foreground text-sm mb-3">No unmastered wrong answers</p>
          <Button size="sm" variant="outline" onClick={loadWrongAnswers}>
            <RefreshCcw className="h-4 w-4 mr-1" />
            Refresh
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden" data-testid="review-panel">
      <div className="px-3 py-2 border-b flex items-center justify-between text-xs text-muted-foreground">
        <span>{wrongAnswers.length} mistakes ready for review</span>
        <Button size="sm" onClick={handleGenerateReview} disabled={generating}>
          {generating ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Sparkles className="h-4 w-4 mr-1" />}
          Generate Review
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {stats && (
          <div className="rounded-lg border bg-card p-4 space-y-3" data-testid="review-stats">
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline">Total: {stats.total}</Badge>
              <Badge variant="outline">Unmastered: {stats.unmastered}</Badge>
              <Badge variant="outline">Mastered: {stats.mastered}</Badge>
            </div>
            {Object.keys(stats.by_category).length > 0 && (
              <div className="flex flex-wrap gap-2">
                {Object.entries(stats.by_category).map(([label, count]) => (
                  <Badge key={label} variant="secondary">
                    {label}: {count}
                  </Badge>
                ))}
              </div>
            )}
            {Object.keys(stats.by_diagnosis).length > 0 && (
              <div className="flex flex-wrap gap-2">
                {Object.entries(stats.by_diagnosis).map(([label, count]) => (
                  <Badge key={label} variant="secondary" className="capitalize">
                    {label.replaceAll("_", " ")}: {count}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        )}

        {reviewMarkdown && (
          <div className="rounded-lg border bg-muted/30 p-4 prose prose-sm max-w-none" data-testid="review-markdown">
            <MarkdownRenderer content={reviewMarkdown} />
          </div>
        )}

        {wrongAnswers.map((item, index) => (
          <div key={item.id} className="rounded-lg border bg-card p-4 space-y-2" data-testid={`wrong-answer-${item.id}`}>
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="text-sm font-medium">{index + 1}. {item.question ?? "Untitled question"}</p>
                <div className="flex gap-2 mt-2 flex-wrap">
                  <Badge variant="outline">{item.question_type ?? "unknown"}</Badge>
                  {item.error_category && <Badge variant="secondary">{item.error_category}</Badge>}
                  {item.diagnosis && (
                    <Badge variant="secondary" className="capitalize">
                      {item.diagnosis.replaceAll("_", " ")}
                    </Badge>
                  )}
                </div>
              </div>
              <Button
                data-testid={`derive-${item.id}`}
                size="sm"
                variant="outline"
                onClick={() => handleDerive(item.id)}
                disabled={derivingId === item.id}
              >
                {derivingId === item.id ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : null}
                Derive
              </Button>
            </div>
            <div className="text-xs text-muted-foreground space-y-1">
              <p><span className="font-medium text-foreground">Your answer:</span> {item.user_answer}</p>
              {item.correct_answer && (
                <p><span className="font-medium text-foreground">Correct answer:</span> {item.correct_answer}</p>
              )}
              {item.error_detail?.related_concept && (
                <p><span className="font-medium text-foreground">Concept:</span> {item.error_detail.related_concept}</p>
              )}
              {item.error_detail?.evidence && (
                <p><span className="font-medium text-foreground">Why it likely happened:</span> {item.error_detail.evidence}</p>
              )}
              {item.explanation && <p>{item.explanation}</p>}
            </div>

            {diagnosticDrafts[item.id] && (
              <div className="rounded-md border bg-muted/20 p-3 space-y-3" data-testid={`diagnostic-${item.id}`}>
                <div>
                  <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-1">Diagnostic check</p>
                  <p className="text-sm font-medium">{diagnosticDrafts[item.id].question}</p>
                </div>

                {diagnosticDrafts[item.id].options ? (
                  <div className="grid gap-2">
                    {Object.entries(diagnosticDrafts[item.id].options ?? {}).map(([key, label]) => (
                      <Button
                        key={key}
                        type="button"
                        variant={diagnosticDrafts[item.id].selectedAnswer === key ? "default" : "outline"}
                        className="justify-start"
                        data-testid={`diagnostic-option-${item.id}-${key}`}
                        disabled={diagnosticDrafts[item.id].pending}
                        onClick={() => handleDiagnosticAnswer(item.id, key)}
                      >
                        {key}. {label}
                      </Button>
                    ))}
                  </div>
                ) : (
                  <div className="space-y-2">
                    <p className="text-xs text-muted-foreground">
                      This diagnostic question is open-ended. Use the API or a future text-input flow to answer it.
                    </p>
                  </div>
                )}

                {(diagnosticDrafts[item.id].diagnosis || item.diagnosis) && (
                  <Badge variant="secondary" className="capitalize" data-testid={`diagnosis-${item.id}`}>
                    {(diagnosticDrafts[item.id].diagnosis || item.diagnosis || "").replaceAll("_", " ")}
                  </Badge>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
