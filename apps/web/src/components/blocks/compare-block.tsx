"use client";

import { useCallback, useEffect, useState } from "react";
import type { AnswerResult } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MarkdownRenderer } from "@/components/shared/markdown-renderer";
import { ExplainStep } from "@/components/practice/explain-step";
import { MissBanner } from "@/components/practice/miss-banner";

export interface CompareBlockProps {
  problemId: string;
  questionText: string;
  options?: Record<string, string> | null;
  correctAnswer?: string | null;
  /** Optional course/track id for the "Add to review" link in the
   *  miss banner (Slice 3 Path B). */
  courseId?: string;
  className?: string;
  onSubmit: (answer: string) => Promise<AnswerResult>;
  onAdvance?: () => void;
}

export function CompareBlock({
  problemId,
  questionText,
  options,
  correctAnswer,
  courseId,
  className,
  onSubmit,
  onAdvance,
}: CompareBlockProps) {
  const [selectedChoice, setSelectedChoice] = useState<string | null>(null);
  const [justification, setJustification] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    setSelectedChoice(null);
    setJustification("");
    setResult(null);
    setSubmitError(null);
  }, [problemId]);

  const choiceKeys = options ? Object.keys(options).sort() : [];
  const hasMinimumJustification = justification.trim().length >= 20;
  const isLocked = submitting || result !== null;
  const submitDisabled =
    isLocked || selectedChoice === null || !hasMinimumJustification;
  const revealedAnswer = result?.correct_answer ?? correctAnswer;

  const handleSubmit = useCallback(async () => {
    if (submitDisabled || !selectedChoice) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const userAnswer = `${selectedChoice.toUpperCase()}: ${justification.trim()}`;
      const res = await onSubmit(userAnswer);
      setResult(res);
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : "Submit failed — try again",
      );
    } finally {
      setSubmitting(false);
    }
  }, [justification, onSubmit, selectedChoice, submitDisabled]);

  return (
    <div
      role="form"
      aria-label="Compare block"
      className={`flex flex-col gap-3 p-4 ${className ?? ""}`.trim()}
      data-testid="compare-block"
    >
      <div className="flex items-center gap-2">
        <Badge variant="outline" className="text-[10px]">
          Compare
        </Badge>
        <span className="text-xs text-muted-foreground">
          Pick one approach and justify it
        </span>
      </div>

      <div
        id={`compare-block-prompt-${problemId}`}
        data-testid="compare-block-prompt"
        className="rounded-md border border-border/60 bg-muted/20 p-3"
      >
        <MarkdownRenderer content={questionText} className="text-sm leading-relaxed" />
      </div>

      {choiceKeys.length > 0 ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {choiceKeys.map((key) => {
            const selected = selectedChoice === key;
            return (
              <button
                key={key}
                type="button"
                disabled={isLocked}
                onClick={() => setSelectedChoice(key)}
                data-testid={`compare-block-choice-${key.toUpperCase()}`}
                className={`rounded-xl border px-4 py-4 text-left transition-colors ${
                  selected
                    ? "border-primary bg-primary/10"
                    : "border-border hover:border-primary/50"
                } disabled:cursor-default disabled:opacity-60`}
              >
                <span className="text-xs font-semibold uppercase text-muted-foreground">
                  {key}
                </span>
                <p className="mt-2 text-sm font-medium">{options?.[key]}</p>
              </button>
            );
          })}
        </div>
      ) : (
        <p role="alert" className="text-xs text-destructive">
          Comparison options are missing for this card.
        </p>
      )}

      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium text-muted-foreground">
          Why did you pick this?
        </span>
        <textarea
          data-testid="compare-block-justify"
          className="min-h-[120px] w-full resize-y rounded-md border border-border bg-muted/30 p-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
          placeholder="Name the reason clearly: performance, clarity, correctness, or idiom."
          value={justification}
          onChange={(e) => setJustification(e.target.value)}
          disabled={isLocked}
        />
      </label>

      <div className="flex items-center gap-2">
        <Button
          type="button"
          size="sm"
          disabled={submitDisabled}
          onClick={() => void handleSubmit()}
          data-testid="compare-block-submit"
        >
          {submitting ? "Submitting..." : "Submit"}
        </Button>
      </div>

      {result ? (
        result.is_correct ? (
          <div
            role="status"
            aria-live="polite"
            className="rounded-md border border-success/40 bg-success/10 p-3"
            data-testid="compare-block-result-correct"
          >
            <p className="text-sm font-medium text-success">Correct</p>
            {result.explanation ? (
              <p className="mt-1 text-xs whitespace-pre-wrap text-muted-foreground">
                {result.explanation}
              </p>
            ) : null}
            <div className="mt-3">
              <ExplainStep problemId={problemId} correct={true} />
            </div>
            {onAdvance ? (
              <div className="mt-3">
                <Button
                  type="button"
                  size="sm"
                  onClick={onAdvance}
                  data-testid="compare-block-next"
                >
                  Next
                </Button>
              </div>
            ) : null}
          </div>
        ) : (
          <div data-testid="compare-block-result-wrong">
            <MissBanner
              problemId={problemId}
              courseId={courseId}
              revealedAnswer={revealedAnswer ?? null}
            >
              {result.explanation ? (
                <p className="text-xs whitespace-pre-wrap text-muted-foreground">
                  {result.explanation}
                </p>
              ) : null}
            </MissBanner>
            {onAdvance ? (
              <div className="mt-3">
                <Button
                  type="button"
                  size="sm"
                  onClick={onAdvance}
                  data-testid="compare-block-next"
                >
                  Next
                </Button>
              </div>
            ) : null}
          </div>
        )
      ) : null}

      {submitError ? (
        <p
          role="alert"
          className="text-xs text-destructive"
          data-testid="compare-block-submit-error"
        >
          {submitError}
        </p>
      ) : null}
    </div>
  );
}

export default CompareBlock;
