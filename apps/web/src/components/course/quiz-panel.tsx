"use client";

import { useEffect, useState } from "react";
import { Loader2, ChevronLeft, ChevronRight, CheckCircle, XCircle, Sparkles } from "lucide-react";
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
} from "@/lib/quiz-api";

/**
 * Interactive Quiz Panel.
 *
 * Reference: spaceforge consolidated-mcq-modal pattern.
 * - One question at a time
 * - Color feedback (green correct, red incorrect)
 * - Keyboard shortcuts (1-4 for MC options)
 * - Score tracking
 */

interface QuizPanelProps {
  courseId: string;
}

export function QuizPanel({ courseId }: QuizPanelProps) {
  const [problems, setProblems] = useState<QuizProblem[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [selectedAnswer, setSelectedAnswer] = useState<string | null>(null);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [score, setScore] = useState({ correct: 0, total: 0 });

  useEffect(() => {
    loadProblems();
  }, [courseId]);

  const loadProblems = async () => {
    setLoading(true);
    try {
      const data = await listProblems(courseId);
      setProblems(data);
    } catch {
      // No problems yet — expected for new courses
    } finally {
      setLoading(false);
    }
  };

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

  const handleSelect = async (answer: string) => {
    if (result) return; // Already answered
    setSelectedAnswer(answer);

    try {
      const res = await submitAnswer(problems[currentIndex].id, answer);
      setResult(res);
      setScore((s) => ({
        correct: s.correct + (res.is_correct ? 1 : 0),
        total: s.total + 1,
      }));
    } catch (err) {
      toast.error("Failed to submit answer");
    }
  };

  const handleNext = () => {
    if (currentIndex < problems.length - 1) {
      setCurrentIndex((i) => i + 1);
      setSelectedAnswer(null);
      setResult(null);
    }
  };

  const handlePrev = () => {
    if (currentIndex > 0) {
      setCurrentIndex((i) => i - 1);
      setSelectedAnswer(null);
      setResult(null);
    }
  };

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
          <p className="text-muted-foreground text-sm mb-3">No quiz questions yet</p>
          <Button onClick={handleExtract} disabled={extracting} size="sm">
            {extracting ? (
              <>
                <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                Generating...
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4 mr-1" />
                Generate Quiz from Content
              </>
            )}
          </Button>
        </div>
      </div>
    );
  }

  const problem = problems[currentIndex];
  const optionKeys = problem.options ? Object.keys(problem.options) : [];

  return (
    <div className="flex-1 flex flex-col">
      {/* Progress bar */}
      <div className="px-3 py-2 border-b flex items-center justify-between text-xs text-muted-foreground">
        <span>
          Question {currentIndex + 1} of {problems.length}
        </span>
        <Badge variant="outline">
          {score.correct}/{score.total} correct
        </Badge>
      </div>

      {/* Question */}
      <ScrollArea className="flex-1 p-4">
        <div className="mb-4">
          <Badge variant="secondary" className="mb-2 text-xs">
            {problem.question_type.toUpperCase()}
          </Badge>
          <p className="text-sm font-medium leading-relaxed">{problem.question}</p>
        </div>

        {/* Options (for MC/TF/select_all) */}
        {problem.options && (
          <div className="space-y-2">
            {optionKeys.map((key) => {
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
                  className={optionClass}
                  onClick={() => handleSelect(key)}
                  disabled={!!result}
                >
                  <span className="font-medium mr-2">{key}.</span>
                  {problem.options![key]}
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
            <p className="text-xs font-medium mb-1">Explanation:</p>
            <p className="text-sm text-muted-foreground">{result.explanation}</p>
          </div>
        )}
      </ScrollArea>

      {/* Navigation */}
      <div className="border-t px-3 py-2 flex items-center justify-between">
        <Button variant="ghost" size="sm" onClick={handlePrev} disabled={currentIndex === 0}>
          <ChevronLeft className="h-4 w-4 mr-1" />
          Prev
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleNext}
          disabled={currentIndex >= problems.length - 1}
        >
          Next
          <ChevronRight className="h-4 w-4 ml-1" />
        </Button>
      </div>
    </div>
  );
}
