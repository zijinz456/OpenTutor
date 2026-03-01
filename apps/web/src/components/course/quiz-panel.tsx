"use client";

import { useEffect, useState, useCallback } from "react";
import { Loader2, ChevronLeft, ChevronRight, CheckCircle, XCircle, Sparkles, Keyboard } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { toast } from "sonner";
import {
  listProblems,
  extractQuiz,
  submitAnswer,
  type QuizProblem,
  type AnswerResult,
} from "@/lib/api";
import { useT } from "@/lib/i18n-context";

/**
 * Interactive Quiz Panel.
 *
 * Reference: spaceforge consolidated-mcq-modal pattern.
 * - One question at a time
 * - Color feedback (green correct, red incorrect)
 * - Keyboard shortcuts (1-4 for MC options, ←/→ for navigation)
 * - Score tracking with accuracy percentage
 */

interface QuizPanelProps {
  courseId: string;
}

export function QuizPanel({ courseId }: QuizPanelProps) {
  const t = useT();
  const [problems, setProblems] = useState<QuizProblem[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [selectedAnswer, setSelectedAnswer] = useState<string | null>(null);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [score, setScore] = useState({ correct: 0, total: 0 });

  const loadProblems = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listProblems(courseId);
      setProblems(data);
    } catch {
      // No problems yet — expected for new courses
    } finally {
      setLoading(false);
    }
  }, [courseId]);

  useEffect(() => {
    loadProblems();
  }, [loadProblems]);

  const handleExtract = async () => {
    setExtracting(true);
    try {
      const res = await extractQuiz(courseId);
      toast.success(`Generated ${res.problems_created} questions`);
      await loadProblems();
    } catch (err) {
      toast.error(`Extraction failed: ${(err as Error).message}`);
    } finally {
      setExtracting(false);
    }
  };

  const handleSelect = useCallback(async (answer: string) => {
    if (result) return; // Already answered
    setSelectedAnswer(answer);

    try {
      const res = await submitAnswer(problems[currentIndex].id, answer);
      setResult(res);
      setScore((s) => ({
        correct: s.correct + (res.is_correct ? 1 : 0),
        total: s.total + 1,
      }));
    } catch {
      toast.error("Failed to submit answer");
    }
  }, [currentIndex, problems, result]);

  const handleNext = useCallback(() => {
    if (currentIndex < problems.length - 1) {
      setCurrentIndex((i) => i + 1);
      setSelectedAnswer(null);
      setResult(null);
    }
  }, [currentIndex, problems.length]);

  const handlePrev = useCallback(() => {
    if (currentIndex > 0) {
      setCurrentIndex((i) => i - 1);
      setSelectedAnswer(null);
      setResult(null);
    }
  }, [currentIndex]);

  // Keyboard shortcuts: 1-4 for options, ←/→ for navigation
  useEffect(() => {
    if (problems.length === 0) return;
    const problem = problems[currentIndex];
    const optionKeys = problem?.options ? Object.keys(problem.options) : [];

    const handler = (e: KeyboardEvent) => {
      // Don't capture when user is typing in an input/textarea
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement
      )
        return;

      // Number keys 1-4 → select option
      const num = parseInt(e.key, 10);
      if (num >= 1 && num <= optionKeys.length && !result) {
        e.preventDefault();
        handleSelect(optionKeys[num - 1]);
        return;
      }

      // Arrow keys → navigate
      if (e.key === "ArrowRight" || e.key === "ArrowDown") {
        e.preventDefault();
        handleNext();
      } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
        e.preventDefault();
        handlePrev();
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [problems, currentIndex, result, handleNext, handlePrev, handleSelect]);

  // Loading state
  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // Empty state
  if (problems.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-4 text-center">
        <div>
          <p className="text-muted-foreground text-sm mb-3">{t("quiz.empty")}</p>
          <Button onClick={handleExtract} disabled={extracting} size="sm">
            {extracting ? (
              <>
                <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                {t("quiz.generating")}
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4 mr-1" />
                {t("quiz.generate")}
              </>
            )}
          </Button>
        </div>
      </div>
    );
  }

  const problem = problems[currentIndex];
  const optionKeys = problem.options ? Object.keys(problem.options) : [];
  const accuracy = score.total > 0 ? Math.round((score.correct / score.total) * 100) : null;

  return (
    <div className="flex-1 flex flex-col" data-testid="quiz-panel">
      {/* Progress bar */}
      <div className="px-3 py-2 border-b flex items-center justify-between text-xs text-muted-foreground">
        <span>
          {t("quiz.question")} {currentIndex + 1} {t("quiz.of")} {problems.length}
        </span>
        <div className="flex items-center gap-2">
          {accuracy !== null && (
            <Badge
              variant="outline"
              className={
                accuracy >= 80
                  ? "border-green-500 text-green-600"
                  : accuracy >= 50
                    ? "border-yellow-500 text-yellow-600"
                    : "border-red-500 text-red-600"
              }
            >
              {accuracy}%
            </Badge>
          )}
          <Badge variant="outline">
            {score.correct}/{score.total} {t("quiz.correct")}
          </Badge>
        </div>
      </div>

      {/* Question */}
      <ScrollArea className="flex-1 p-4">
        <div className="mb-4" data-testid="quiz-question">
          <div className="flex items-center gap-2 mb-2">
            <Badge variant="secondary" className="text-xs">
              {problem.question_type.toUpperCase()}
            </Badge>
          </div>
          <p className="text-sm font-medium leading-relaxed">{problem.question}</p>
        </div>

        {/* Options (for MC/TF/select_all) */}
        {problem.options && (
          <div className="space-y-2">
            {optionKeys.map((key, idx) => {
              const isSelected = selectedAnswer === key;
              const isCorrect = result && result.correct_answer?.startsWith(key);
              const isWrong = result && isSelected && !result.is_correct;

              let optionClass =
                "w-full text-left px-3 py-2 rounded-md border text-sm transition-colors ";
              if (result) {
                if (isCorrect) optionClass += "border-green-500 bg-green-50 dark:bg-green-950";
                else if (isWrong) optionClass += "border-red-500 bg-red-50 dark:bg-red-950";
                else optionClass += "border-border opacity-60";
              } else if (isSelected) {
                optionClass += "border-primary bg-primary/5";
              } else {
                optionClass += "border-border hover:border-primary/50 hover:bg-muted/50 cursor-pointer";
              }

              return (
                <button
                  key={key}
                  data-testid={`quiz-option-${key}`}
                  className={optionClass}
                  onClick={() => handleSelect(key)}
                  disabled={!!result}
                >
                  <span className="inline-flex items-center">
                    <span className="font-medium mr-2">{key}.</span>
                    {problem.options![key]}
                    {!result && (
                      <kbd className="ml-auto text-[10px] text-muted-foreground/50 bg-muted px-1 rounded font-mono">
                        {idx + 1}
                      </kbd>
                    )}
                  </span>
                  {result && isCorrect && (
                    <CheckCircle className="inline h-4 w-4 ml-2 text-green-600" />
                  )}
                  {result && isWrong && (
                    <XCircle className="inline h-4 w-4 ml-2 text-red-600" />
                  )}
                </button>
              );
            })}
          </div>
        )}

        {/* Explanation (after answering) */}
        {result && result.explanation && (
          <div className="mt-4 p-3 bg-muted rounded-md">
            <p className="text-xs font-medium mb-1">{t("quiz.explanation")}</p>
            <p className="text-sm text-muted-foreground">{result.explanation}</p>
          </div>
        )}

        {/* Next hint after answering */}
        {result && currentIndex < problems.length - 1 && (
          <p className="mt-3 text-xs text-muted-foreground/60 text-center">
            Press <kbd className="px-1 bg-muted rounded font-mono text-[10px]">&rarr;</kbd> for next question
          </p>
        )}
      </ScrollArea>

      {/* Navigation */}
      <div className="border-t px-3 py-2 flex items-center justify-between">
        <Button variant="ghost" size="sm" onClick={handlePrev} disabled={currentIndex === 0}>
          <ChevronLeft className="h-4 w-4 mr-1" />
          {t("quiz.prev")}
        </Button>
        <div className="flex items-center gap-1 text-[10px] text-muted-foreground/40">
          <Keyboard className="h-3 w-3" />
          1-{optionKeys.length} select &middot; &larr;&rarr; navigate
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleNext}
          disabled={currentIndex >= problems.length - 1}
        >
          {t("quiz.next")}
          <ChevronRight className="h-4 w-4 ml-1" />
        </Button>
      </div>
    </div>
  );
}
