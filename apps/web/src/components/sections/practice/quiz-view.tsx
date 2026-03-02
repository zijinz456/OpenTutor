"use client";

import { useCallback, useEffect, useState } from "react";
import { useT } from "@/lib/i18n-context";
import {
  listProblems,
  submitAnswer,
  listGeneratedQuizBatches,
  type QuizProblem,
  type AnswerResult,
  type GeneratedQuizBatchSummary,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface QuizViewProps {
  courseId: string;
}

export function QuizView({ courseId }: QuizViewProps) {
  const t = useT();

  const [batches, setBatches] = useState<GeneratedQuizBatchSummary[]>([]);
  const [selectedBatch, setSelectedBatch] = useState<string>("all");
  const [problems, setProblems] = useState<QuizProblem[]>([]);
  const [currentIdx, setCurrentIdx] = useState(0);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const [result, setResult] = useState<AnswerResult | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [b, p] = await Promise.all([
        listGeneratedQuizBatches(courseId),
        listProblems(courseId),
      ]);
      setBatches(b);
      setProblems(p);
    } catch { /* empty state fallback */ }
    finally { setLoading(false); }
  }, [courseId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  useEffect(() => { setSelectedOption(null); setResult(null); }, [currentIdx, selectedBatch]);

  const filtered = selectedBatch === "all"
    ? problems
    : problems.filter((p) => p.id.startsWith(selectedBatch));
  const total = filtered.length;
  const problem = filtered[currentIdx] ?? null;

  const handleOptionClick = async (option: string) => {
    if (result || submitting) return;
    setSelectedOption(option);
    setSubmitting(true);
    try {
      const res = await submitAnswer(problem!.id, option);
      setResult(res);
    } catch {
      setSelectedOption(null);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="h-4 w-32 bg-muted animate-pulse rounded" />
      </div>
    );
  }

  if (problems.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
        <h3 className="text-sm font-medium mb-1">{t("quiz.title")}</h3>
        <p className="text-xs text-muted-foreground max-w-xs">
          {t("quiz.empty")}
        </p>
      </div>
    );
  }

  const optionKeys = problem?.options ? Object.keys(problem.options).sort() : [];

  const optionStyle = (key: string) => {
    if (!result) {
      return key === selectedOption
        ? "border-primary bg-primary/10"
        : "border-border hover:border-primary/50";
    }
    if (key === result.correct_answer) return "border-green-500 bg-green-500/10";
    if (key === selectedOption && !result.is_correct)
      return "border-destructive bg-destructive/10";
    return "border-border opacity-60";
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b shrink-0">
        {batches.length > 0 && (
          <Select
            value={selectedBatch}
            onValueChange={(v) => { setSelectedBatch(v); setCurrentIdx(0); }}
          >
            <SelectTrigger size="sm" className="text-xs max-w-[180px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("quiz.title")}</SelectItem>
              {batches.map((b) => (
                <SelectItem key={b.batch_id} value={b.batch_id}>
                  {b.title || b.batch_id.slice(0, 8)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <span className="ml-auto text-xs text-muted-foreground">
          {total > 0
            ? `${t("quiz.question")} ${currentIdx + 1} ${t("quiz.of")} ${total}`
            : t("quiz.empty")}
        </span>
      </div>

      {/* problem body */}
      {problem ? (
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          <p className="text-sm font-medium leading-relaxed">{problem.question}</p>

          <div className="space-y-2">
            {optionKeys.map((key) => (
              <button
                key={key}
                disabled={!!result || submitting}
                onClick={() => handleOptionClick(key)}
                className={`w-full text-left rounded-md border px-3 py-2 text-sm transition-colors ${optionStyle(key)} disabled:cursor-default`}
              >
                <span className="font-medium mr-2">{key.toUpperCase()}.</span>
                {problem.options![key]}
              </button>
            ))}
          </div>

          {result && (
            <div className="space-y-1.5 pt-1">
              <Badge variant={result.is_correct ? "default" : "destructive"}>
                {result.is_correct ? t("quiz.correct") : result.correct_answer?.toUpperCase()}
              </Badge>
              {result.explanation && (
                <p className="text-xs text-muted-foreground leading-relaxed">
                  {t("quiz.explanation")} {result.explanation}
                </p>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center p-8">
          <p className="text-xs text-muted-foreground">{t("quiz.empty")}</p>
        </div>
      )}

      {/* navigation */}
      <div className="flex items-center justify-between px-3 py-2 border-t shrink-0">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={currentIdx === 0}
          onClick={() => setCurrentIdx((i) => i - 1)}
        >
          {t("quiz.prev")}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={currentIdx >= total - 1}
          onClick={() => setCurrentIdx((i) => i + 1)}
        >
          {t("quiz.next")}
        </Button>
      </div>
    </div>
  );
}
