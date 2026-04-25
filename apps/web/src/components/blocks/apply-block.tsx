"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTheme } from "next-themes";
import type { AnswerResult } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MarkdownRenderer } from "@/components/shared/markdown-renderer";
import { ExplainStep } from "@/components/practice/explain-step";
import { MissBanner } from "@/components/practice/miss-banner";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => (
    <div
      role="status"
      aria-label="Loading editor"
      className="h-[320px] w-full rounded-md border border-border bg-muted/30 animate-pulse"
    />
  ),
});

export interface ApplyBlockProps {
  problemId: string;
  questionText: string;
  starterCode?: string;
  language?: string;
  correctAnswer?: string | null;
  /** Optional course/track id for the "Add to review" link in the
   *  miss banner (Slice 3 Path B). */
  courseId?: string;
  className?: string;
  onSubmit: (answer: string) => Promise<AnswerResult>;
  onAdvance?: () => void;
}

export function ApplyBlock({
  problemId,
  questionText,
  starterCode = "",
  language = "python",
  correctAnswer,
  courseId,
  className,
  onSubmit,
  onAdvance,
}: ApplyBlockProps) {
  const { resolvedTheme } = useTheme();
  const monacoTheme = resolvedTheme === "dark" ? "vs-dark" : "light";
  const [editorValue, setEditorValue] = useState(starterCode);
  const editorRef = useRef<{ setValue: (value: string) => void } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    setEditorValue(starterCode);
    editorRef.current?.setValue(starterCode);
    setResult(null);
    setSubmitError(null);
  }, [problemId, starterCode]);

  const isLocked = submitting || result !== null;
  const revealedAnswer = result?.correct_answer ?? correctAnswer;

  const handleSubmit = useCallback(async () => {
    if (submitting) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const res = await onSubmit(editorValue);
      setResult(res);
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : "Couldn't submit. Retry?",
      );
    } finally {
      setSubmitting(false);
    }
  }, [editorValue, onSubmit, submitting]);

  return (
    <div
      role="form"
      aria-label="Apply block"
      className={`flex flex-col gap-3 p-4 ${className ?? ""}`.trim()}
      data-testid="apply-block"
    >
      <div className="flex items-center gap-2">
        <Badge variant="outline" className="text-[10px]">
          Apply
        </Badge>
        <span className="text-xs text-muted-foreground">
          Rewrite using the target feature
        </span>
      </div>

      <div
        id={`apply-block-prompt-${problemId}`}
        data-testid="apply-block-prompt"
        className="rounded-md border border-border/60 bg-muted/20 p-3"
      >
        <MarkdownRenderer content={questionText} className="text-sm leading-relaxed" />
      </div>

      <div
        data-monaco-editor-root
        data-testid="apply-block-editor"
        className="overflow-hidden rounded-md border border-border"
      >
        <MonacoEditor
          height={320}
          defaultLanguage={language}
          defaultValue={starterCode}
          theme={monacoTheme}
          onMount={(editor) => {
            editorRef.current = {
              setValue: (value: string) => editor.setValue(value),
            };
            editor.focus();
          }}
          onChange={(value) => {
            setEditorValue(value ?? "");
          }}
          options={{
            readOnly: isLocked,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            fontSize: 14,
            tabSize: 4,
            automaticLayout: true,
            wordWrap: "on",
            lineNumbers: "on",
            renderLineHighlight: "line",
            padding: { top: 8, bottom: 8 },
          }}
          aria-label="Python code editor"
        />
      </div>

      <div className="flex items-center gap-2">
        <Button
          type="button"
          size="sm"
          disabled={isLocked}
          onClick={() => void handleSubmit()}
          data-testid="apply-block-submit"
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
            data-testid="apply-block-result-correct"
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
                  data-testid="apply-block-next"
                >
                  Next
                </Button>
              </div>
            ) : null}
          </div>
        ) : (
          <div data-testid="apply-block-result-wrong">
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
                <details className="rounded-md border border-border/60 p-2">
                  <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
                    Reference answer
                  </summary>
                  <pre className="mt-2 whitespace-pre-wrap rounded-md bg-muted/30 px-3 py-2 text-xs font-mono">
                    {revealedAnswer}
                  </pre>
                </details>
              ) : null}
            </MissBanner>
            {onAdvance ? (
              <div className="mt-3">
                <Button
                  type="button"
                  size="sm"
                  onClick={onAdvance}
                  data-testid="apply-block-next"
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
          data-testid="apply-block-submit-error"
        >
          {submitError}
        </p>
      ) : null}
    </div>
  );
}

export default ApplyBlock;
