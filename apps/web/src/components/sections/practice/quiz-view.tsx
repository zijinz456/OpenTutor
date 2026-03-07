"use client";

import { useCallback, useEffect, useState } from "react";
import { useT } from "@/lib/i18n-context";
import {
  extractQuiz,
  listProblems,
  submitAnswer,
  type QuizProblem,
  type AnswerResult,
} from "@/lib/api";
import { useWorkspaceStore } from "@/store/workspace";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { AiFeatureBlocked } from "@/components/shared/ai-feature-blocked";
import { updateUnlockContext, getUnlockContext } from "@/lib/block-system/feature-unlock";

interface QuizViewProps {
  courseId: string;
  aiActionsEnabled?: boolean;
}

export function QuizView({ courseId, aiActionsEnabled = true }: QuizViewProps) {
  const t = useT();
  const refreshKey = useWorkspaceStore((s) => s.sectionRefreshKey["practice"]);
  const [problems, setProblems] = useState<QuizProblem[]>([]);
  const [currentIdx, setCurrentIdx] = useState(0);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [extractStatus, setExtractStatus] = useState<string | null>(null);
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [score, setScore] = useState({ correct: 0, total: 0 });

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const items = await listProblems(courseId);
      setProblems(items);
    } catch {
      setProblems([]);
    } finally {
      setLoading(false);
    }
  }, [courseId]);

  useEffect(() => {
    void fetchData();
  }, [fetchData, refreshKey]);

  useEffect(() => {
    setSelectedOption(null);
    setResult(null);
  }, [currentIdx]);

  const handleExtract = async () => {
    setExtracting(true);
    setExtractStatus(null);
    try {
      const res = await extractQuiz(courseId);
      setExtractStatus(`Generated ${res.problems_created} questions`);
      await fetchData();
    } catch (error) {
      setExtractStatus(`Extraction failed: ${(error as Error).message}`);
    } finally {
      setExtracting(false);
    }
  };

  const handleOptionClick = async (option: string) => {
    if (result || submitting) return;
    setSelectedOption(option);
    setSubmitting(true);
    try {
      const res = await submitAnswer(problems[currentIdx].id, option);
      setResult(res);
      setScore((prev) => ({
        correct: prev.correct + (res.is_correct ? 1 : 0),
        total: prev.total + 1,
      }));
      // Track feature-unlock context
      const ctx = getUnlockContext(courseId, 0);
      updateUnlockContext(courseId, {
        practiceAttempts: ctx.practiceAttempts + 1,
        hasWrongAnswer: ctx.hasWrongAnswer || !res.is_correct,
      });
    } catch {
      setSelectedOption(null);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center p-8" data-testid="quiz-panel">
        <div className="h-4 w-32 bg-muted animate-pulse rounded" />
      </div>
    );
  }

  if (problems.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center" data-testid="quiz-panel">
        <h3 className="text-sm font-medium mb-1">{t("quiz.title")}</h3>
        <p className="text-xs text-muted-foreground max-w-xs">{t("quiz.empty")}</p>
        {!aiActionsEnabled ? <AiFeatureBlocked compact className="mt-3 w-full max-w-sm text-left" /> : null}
        <Button className="mt-3" size="sm" onClick={() => void handleExtract()} disabled={!aiActionsEnabled || extracting}>
          {extracting ? `${t("quiz.generating")}...` : t("quiz.generate")}
        </Button>
        {extractStatus ? (
          <p className="mt-3 text-xs text-muted-foreground" data-testid="quiz-extract-status">
            {extractStatus}
          </p>
        ) : null}
      </div>
    );
  }

  const problem = problems[currentIdx];
  const optionKeys = problem.options ? Object.keys(problem.options).sort() : [];
  const accuracy = score.total > 0 ? Math.round((score.correct / score.total) * 100) : null;

  const optionStyle = (key: string) => {
    if (!result) {
      return key === selectedOption
        ? "border-primary bg-primary/10"
        : "border-border hover:border-primary/50";
    }
    if (key === result.correct_answer) return "border-green-500 bg-green-500/10";
    if (key === selectedOption && !result.is_correct) {
      return "border-destructive bg-destructive/10";
    }
    return "border-border opacity-60";
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden" data-testid="quiz-panel">
      <div className="flex items-center gap-2 px-3 py-2 border-b shrink-0">
        {accuracy !== null ? <Badge variant="outline">{accuracy}%</Badge> : null}
        <span className="ml-auto text-xs text-muted-foreground">
          {t("quiz.question")} {currentIdx + 1} {t("quiz.of")} {problems.length}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <p className="text-sm font-medium leading-relaxed" data-testid="quiz-question">
          {problem.question}
        </p>

        <div className="space-y-2">
          {optionKeys.map((key) => (
            <button
              key={key}
              data-testid={`quiz-option-${key}`}
              disabled={!!result || submitting}
              onClick={() => void handleOptionClick(key)}
              className={`w-full text-left rounded-md border px-3 py-2 text-sm transition-colors ${optionStyle(key)} disabled:cursor-default`}
            >
              <span className="font-medium mr-2">{key.toUpperCase()}.</span>
              {problem.options?.[key]}
            </button>
          ))}
        </div>

        {result?.explanation ? (
          <div className="space-y-1.5 pt-1">
            <Badge variant={result.is_correct ? "default" : "destructive"}>
              {result.is_correct ? t("quiz.correct") : result.correct_answer?.toUpperCase()}
            </Badge>
            <p className="text-xs text-muted-foreground leading-relaxed">
              {t("quiz.explanation")} {result.explanation}
            </p>
          </div>
        ) : null}
      </div>

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
          disabled={currentIdx >= problems.length - 1}
          onClick={() => setCurrentIdx((i) => i + 1)}
        >
          {t("quiz.next")}
        </Button>
      </div>
    </div>
  );
}
