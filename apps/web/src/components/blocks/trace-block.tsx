"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { AnswerResult } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MarkdownRenderer } from "@/components/shared/markdown-renderer";
import { ExplainStep } from "@/components/practice/explain-step";
import { MissBanner } from "@/components/practice/miss-banner";

export interface TraceBlockProps {
  problemId: string;
  questionText: string;
  correctAnswer?: string | null;
  /** Optional course/track id for the "Add to review" link in the
   *  miss banner. When absent, the link is suppressed but the banner
   *  + ExplainStep still render (Slice 3 Path B). */
  courseId?: string;
  className?: string;
  onSubmit: (answer: string) => Promise<AnswerResult>;
  onAdvance?: () => void;
}

export function TraceBlock({
  problemId,
  questionText,
  correctAnswer,
  courseId,
  className,
  onSubmit,
  onAdvance,
}: TraceBlockProps) {
  const [answer, setAnswer] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const startedAtRef = useRef(Date.now());

  useEffect(() => {
    setAnswer("");
    setResult(null);
    setSubmitError(null);
    startedAtRef.current = Date.now();
  }, [problemId]);

  const isLocked = submitting || result !== null;

  const handleSubmit = useCallback(async () => {
    if (submitting) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const res = await onSubmit(answer);
      setResult(res);
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : "Submit failed — try again",
      );
    } finally {
      setSubmitting(false);
    }
  }, [answer, onSubmit, submitting]);

  const revealedAnswer = result?.correct_answer ?? correctAnswer;

  return (
    <div
      role="form"
      aria-label="Trace block"
      className={`flex flex-col gap-3 p-4 ${className ?? ""}`.trim()}
      data-testid="trace-block"
    >
      <div className="flex items-center gap-2">
        <Badge variant="outline" className="text-[10px]">
          Trace
        </Badge>
        <span className="text-xs text-muted-foreground">
          Predict the exact output
        </span>
      </div>

      <div
        id={`trace-block-prompt-${problemId}`}
        data-testid="trace-block-prompt"
        className="rounded-md border border-border/60 bg-muted/20 p-3"
      >
        <MarkdownRenderer content={questionText} className="text-sm leading-relaxed" />
      </div>

      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium text-muted-foreground">
          Output prediction
        </span>
        <textarea
          data-testid="trace-block-answer"
          className="min-h-[120px] w-full resize-y rounded-md border border-border bg-muted/30 p-3 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
          placeholder="Type the exact output. Whitespace and newlines matter."
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          disabled={isLocked}
          spellCheck={false}
        />
      </label>

      <p className="text-xs text-muted-foreground">
        Type the exact output. Whitespace and newlines matter.
      </p>

      <div className="flex items-center gap-2">
        <Button
          type="button"
          size="sm"
          disabled={isLocked}
          onClick={() => void handleSubmit()}
          data-testid="trace-block-submit"
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
            data-testid="trace-block-result-correct"
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
                  data-testid="trace-block-next"
                >
                  Next
                </Button>
              </div>
            ) : null}
          </div>
        ) : (
          <div data-testid="trace-block-result-wrong">
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
              {revealedAnswer ? (
                <div>
                  <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    Correct answer
                  </p>
                  <pre className="mt-1 rounded-md bg-muted/30 px-3 py-2 text-xs font-mono whitespace-pre-wrap">
                    {revealedAnswer}
                  </pre>
                </div>
              ) : null}
            </MissBanner>
            {onAdvance ? (
              <div className="mt-3">
                <Button
                  type="button"
                  size="sm"
                  onClick={onAdvance}
                  data-testid="trace-block-next"
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
          data-testid="trace-block-submit-error"
        >
          {submitError}
        </p>
      ) : null}
    </div>
  );
}

export default TraceBlock;
