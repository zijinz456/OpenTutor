"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { MarkdownRenderer } from "@/components/course/markdown-renderer";
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

type ViewMode = "all" | "by_category" | "by_diagnosis";

const DIAGNOSIS_COLORS: Record<string, string> = {
  fundamental_gap: "bg-destructive/10 text-destructive border-destructive/20",
  trap_vulnerability: "bg-warning-muted text-warning border-warning/20",
  carelessness: "bg-warning-muted text-warning border-warning/20",
  mastered: "bg-success-muted text-success border-success/20",
};

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
  const [viewMode, setViewMode] = useState<ViewMode>("all");
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const [markingId, setMarkingId] = useState<string | null>(null);
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

  const groupedItems = useMemo(() => {
    const key = viewMode === "by_category" ? "error_category" : viewMode === "by_diagnosis" ? "diagnosis" : null;
    if (!key) return null;
    const groups: Record<string, WrongAnswer[]> = {};
    for (const item of wrongAnswers) {
      const groupKey = (item[key] as string | null) || "uncategorized";
      (groups[groupKey] ??= []).push(item);
    }
    return groups;
  }, [wrongAnswers, viewMode]);

  const toggleGroup = (group: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(group)) next.delete(group);
      else next.add(group);
      return next;
    });
  };

  const handleMarkMastered = async (item: WrongAnswer) => {
    if (!item.correct_answer) {
      toast.error("No correct answer available to mark as mastered");
      return;
    }
    setMarkingId(item.id);
    try {
      await retryWrongAnswer(item.id, item.correct_answer);
      toast.success("Marked as mastered");
      await loadWrongAnswers();
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
      <div className="flex-1 flex items-center justify-center" data-testid="review-panel">
        <span className="text-sm animate-pulse text-muted-foreground">...</span>
      </div>
    );
  }

  if (wrongAnswers.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-4 text-center" data-testid="review-panel">
        <div>
          <p className="text-muted-foreground text-sm mb-3">No unmastered wrong answers</p>
          <Button size="sm" variant="outline" onClick={loadWrongAnswers}>
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
          {generating ? <span className="animate-pulse mr-1">...</span> : null}
          Generate Review
        </Button>
      </div>

      <div className="px-3 py-1.5 border-b flex items-center gap-1 shrink-0">
        {(["all", "by_category", "by_diagnosis"] as ViewMode[]).map((mode) => (
          <Button
            key={mode}
            variant={viewMode === mode ? "secondary" : "ghost"}
            size="sm"
            className="text-xs h-7 px-2"
            onClick={() => { setViewMode(mode); setCollapsedGroups(new Set()); }}
          >
            {mode === "all" ? "All" : mode === "by_category" ? "By Category" : "By Diagnosis"}
          </Button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {stats && (
          <div className="rounded-lg border bg-card p-4 space-y-3" data-testid="review-stats">
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline">Total: {stats.total}</Badge>
              <Badge variant="outline">Unmastered: {stats.unmastered}</Badge>
              <Badge variant="outline">Mastered: {stats.mastered}</Badge>
            </div>
            {viewMode === "all" && Object.keys(stats.by_category).length > 0 && (
              <div className="flex flex-wrap gap-2">
                {Object.entries(stats.by_category).map(([label, count]) => (
                  <Badge key={label} variant="secondary">
                    {label}: {count}
                  </Badge>
                ))}
              </div>
            )}
            {viewMode === "all" && Object.keys(stats.by_diagnosis).length > 0 && (
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

        {viewMode !== "all" && groupedItems && Object.entries(groupedItems).map(([group, items]) => (
          <div key={group} className="rounded-lg border bg-card overflow-hidden">
            <button
              type="button"
              onClick={() => toggleGroup(group)}
              className={`w-full text-left px-4 py-2.5 flex items-center gap-2 text-sm font-medium hover:bg-muted/50 transition-colors ${viewMode === "by_diagnosis" ? DIAGNOSIS_COLORS[group] ?? "bg-muted text-muted-foreground" : ""}`}
            >
              <span className="w-4 h-4 shrink-0 text-xs font-bold">{collapsedGroups.has(group) ? "\u25B6" : "\u25BC"}</span>
              <span className="capitalize">{group.replaceAll("_", " ")}</span>
              <Badge variant="outline" className="ml-auto">{items.length}</Badge>
            </button>
            {!collapsedGroups.has(group) && (
              <div className="p-3 space-y-3 border-t">
                {items.map((item, index) => renderWrongAnswerCard(item, index))}
              </div>
            )}
          </div>
        ))}

        {viewMode === "all" && wrongAnswers.map((item, index) => renderWrongAnswerCard(item, index))}
      </div>
    </div>
  );

  function renderWrongAnswerCard(item: WrongAnswer, index: number) {
    return (
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
          <div className="flex items-center gap-1 shrink-0">
            <Button
              size="sm"
              variant="ghost"
              className="text-success hover:text-success hover:bg-success-muted"
              onClick={() => void handleMarkMastered(item)}
              disabled={markingId === item.id || !item.correct_answer}
              title="Mark as mastered"
            >
              {markingId === item.id ? <span className="animate-pulse">...</span> : <span className="font-bold">{"\u2713"}</span>}
            </Button>
            <Button
              data-testid={`derive-${item.id}`}
              size="sm"
              variant="outline"
              onClick={() => handleDerive(item.id)}
              disabled={derivingId === item.id}
            >
              {derivingId === item.id ? <span className="animate-pulse mr-1">...</span> : null}
              Derive
            </Button>
          </div>
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
    );
  }
}
