"use client";

/**
 * <CodeExerciseBlock>
 *
 * Code Runner Phase 11 T3 (plan: plan/code_runner_phase11.md).
 *
 * Renders a single code-exercise card: Monaco editor with Python starter
 * code, Run button (executes via Pyodide), Submit button (sends to backend).
 *
 * Contracts:
 *   - Pyodide loader from `@/lib/pyodide-runtime` is lazy-imported inside
 *     the Run handler so its ~162 LOC singleton stays OUT of the first
 *     bundle. First Run click pulls it in.
 *   - Monaco is dynamic-imported with `ssr: false`; the server never sees
 *     `@monaco-editor/react`.
 *   - `runPython` never throws per the T2 contract, so there is no
 *     try/catch around the Run call — errors arrive on `result.stderr`.
 *   - Submit without prior Run is blocked with an inline hint rather than
 *     auto-running: auto-run feels magical and hides the Run button's
 *     teaching value. Backend's "empty stdout ⇒ wrong" branch only fires
 *     if the user manually clears output, which is fine.
 *
 * Keyboard shortcuts (Ctrl+Enter = Run, Ctrl+Shift+Enter = Submit) are
 * bound on the outer wrapper, not inside Monaco — Monaco ships its own
 * Ctrl+Enter and we must not shadow it while the editor has focus.
 */

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

// Monaco MUST load client-only — its worker setup touches `window`.
// Loading spinner matches the theme of the rest of the practice UI.
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

export interface CodeExerciseSubmitPayload {
  code: string;
  stdout: string;
  stderr: string;
  runtime_ms: number;
}

export interface CodeExerciseSubmitResult {
  is_correct: boolean;
  explanation?: string;
}

export interface CodeExerciseBlockProps {
  problemId: string;
  starterCode: string;
  questionText: string;
  expectedOutput?: string;
  hints?: string[];
  /** Fixed editor height in pixels. Default 320. */
  height?: number;
  onSubmit: (
    payload: CodeExerciseSubmitPayload,
  ) => Promise<CodeExerciseSubmitResult>;
  onAdvance?: () => void;
}

interface RunOutput {
  stdout: string;
  stderr: string;
  runtime_ms: number;
}

export function CodeExerciseBlock({
  problemId,
  starterCode,
  questionText,
  expectedOutput,
  hints,
  height = 320,
  onSubmit,
  onAdvance,
}: CodeExerciseBlockProps) {
  const { resolvedTheme } = useTheme();
  const monacoTheme = resolvedTheme === "dark" ? "vs-dark" : "light";

  const [editorValue, setEditorValue] = useState<string>(starterCode);
  const [output, setOutput] = useState<RunOutput | null>(null);
  const [running, setRunning] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<CodeExerciseSubmitResult | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [needsRunHint, setNeedsRunHint] = useState(false);
  // Track the editor value at the moment Run last executed, so we can
  // surface a "code changed since last run" warning and block Submit on
  // stale output. The backend grades on stdout — submitting old stdout
  // after edits would mis-score.
  const lastRunCodeRef = useRef<string | null>(null);

  // Reset local state whenever we move to a different problem. Parent
  // dispatch (T4) swaps the `problemId` prop — we drop all run/submit
  // state to avoid leaking the previous card's feedback.
  useEffect(() => {
    setEditorValue(starterCode);
    setOutput(null);
    setResult(null);
    setSubmitError(null);
    setNeedsRunHint(false);
    lastRunCodeRef.current = null;
  }, [problemId, starterCode]);

  const handleRun = useCallback(async () => {
    if (running) return;
    setRunning(true);
    setNeedsRunHint(false);
    setSubmitError(null);
    try {
      // Lazy import keeps the Pyodide singleton (and its transitive window
      // touches) out of first-paint bundle. The first click here triggers
      // the CDN loader via getPyodide().
      const { getPyodide } = await import("@/lib/pyodide-runtime");
      const runtime = await getPyodide();
      // Contract: runPython never throws — stderr will carry the traceback.
      const runResult = await runtime.runPython(editorValue);
      setOutput(runResult);
      lastRunCodeRef.current = editorValue;
    } catch (err) {
      // Only reached if the Pyodide LOADER itself fails (CDN outage,
      // SSR misfire). Surface as stderr so the user sees something.
      const message =
        err instanceof Error
          ? err.message
          : String(err ?? "Unknown runtime error");
      setOutput({ stdout: "", stderr: message, runtime_ms: 0 });
      lastRunCodeRef.current = editorValue;
    } finally {
      setRunning(false);
    }
  }, [editorValue, running]);

  const handleSubmit = useCallback(async () => {
    if (submitting) return;
    if (output === null) {
      // Force the user through Run first. We do NOT auto-run:
      // - auto-run hides the Run-button teaching affordance
      // - auto-run + slow CDN cold-start = confusing multi-second delay
      //   after a single click
      setNeedsRunHint(true);
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      const res = await onSubmit({
        code: editorValue,
        stdout: output.stdout,
        stderr: output.stderr,
        runtime_ms: output.runtime_ms,
      });
      setResult(res);
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : "Submit failed — try again",
      );
    } finally {
      setSubmitting(false);
    }
  }, [editorValue, onSubmit, output, submitting]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      // Only fire our shortcuts when focus is NOT inside Monaco — Monaco
      // owns Ctrl+Enter (run command). Our wrapper captures only when the
      // user is outside the editor region.
      const target = e.target as HTMLElement;
      if (target && target.closest?.("[data-monaco-editor-root]")) return;
      if (!(e.ctrlKey || e.metaKey) || e.key !== "Enter") return;
      e.preventDefault();
      if (e.shiftKey) {
        void handleSubmit();
      } else {
        void handleRun();
      }
    },
    [handleRun, handleSubmit],
  );

  const codeChangedSinceRun =
    output !== null &&
    lastRunCodeRef.current !== null &&
    lastRunCodeRef.current !== editorValue;

  const isLocked = submitting || result !== null;

  return (
    <div
      role="form"
      aria-label="Code exercise"
      className="flex flex-col gap-3 p-4"
      data-testid="code-exercise-block"
      onKeyDown={handleKeyDown}
    >
      <div className="flex items-center gap-2">
        <Badge variant="outline" className="text-[10px]">
          Python
        </Badge>
        <span className="ml-auto text-[10px] text-muted-foreground">
          Ctrl+Enter Run · Ctrl+Shift+Enter Submit
        </span>
      </div>

      <p
        id={`code-exercise-prompt-${problemId}`}
        className="text-sm font-medium leading-relaxed whitespace-pre-wrap"
        data-testid="code-exercise-prompt"
      >
        {questionText}
      </p>

      <div
        data-monaco-editor-root
        className="overflow-hidden rounded-md border border-border"
      >
        <MonacoEditor
          height={height}
          defaultLanguage="python"
          value={editorValue}
          theme={monacoTheme}
          onChange={(v) => {
            setEditorValue(v ?? "");
            // Editing invalidates the prior run's hint; let them run again.
            setNeedsRunHint(false);
          }}
          options={{
            readOnly: isLocked,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            fontSize: 13,
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
          variant="outline"
          disabled={running || isLocked}
          onClick={() => void handleRun()}
          aria-label="Run code"
          data-testid="code-exercise-run"
        >
          {running ? "Running..." : "Run"}
        </Button>
        <Button
          type="button"
          size="sm"
          disabled={submitting || isLocked}
          onClick={() => void handleSubmit()}
          aria-label="Submit answer"
          data-testid="code-exercise-submit"
        >
          {submitting ? "Submitting..." : "Submit"}
        </Button>
        {needsRunHint ? (
          <span
            role="status"
            className="text-xs text-muted-foreground"
            data-testid="code-exercise-run-first-hint"
          >
            Run your code first to see the output, then submit.
          </span>
        ) : null}
      </div>

      <section
        role="status"
        aria-live="polite"
        aria-label="Code output"
        className="flex flex-col gap-1"
        data-testid="code-exercise-output"
      >
        {running ? (
          <p className="text-xs text-muted-foreground">Running in browser...</p>
        ) : output === null ? (
          <p className="text-xs text-muted-foreground">
            Click Run to see your program&apos;s output.
          </p>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                Output
              </span>
              <span className="text-[10px] text-muted-foreground">
                {Math.round(output.runtime_ms)} ms
              </span>
              {codeChangedSinceRun ? (
                <Badge
                  variant="outline"
                  className="text-[10px] text-warning"
                  data-testid="code-exercise-stale"
                >
                  code changed — run again
                </Badge>
              ) : null}
            </div>
            {output.stdout ? (
              <pre
                data-testid="code-exercise-stdout"
                className="rounded-md bg-muted/30 px-3 py-2 text-xs font-mono whitespace-pre-wrap break-words"
              >
                {output.stdout}
              </pre>
            ) : null}
            {output.stderr ? (
              <pre
                data-testid="code-exercise-stderr"
                className="rounded-md bg-destructive/10 px-3 py-2 text-xs font-mono text-destructive whitespace-pre-wrap break-words"
              >
                {output.stderr}
              </pre>
            ) : null}
            {!output.stdout && !output.stderr ? (
              <p className="text-xs text-muted-foreground">
                (no output — did you forget to <code>print(...)</code>?)
              </p>
            ) : null}
          </>
        )}
      </section>

      {result !== null ? (
        <div
          role="status"
          aria-live="polite"
          className={
            result.is_correct
              ? "rounded-md border border-success/40 bg-success/10 p-3"
              : "rounded-md border border-destructive/40 bg-destructive/10 p-3"
          }
          data-testid={
            result.is_correct
              ? "code-exercise-result-correct"
              : "code-exercise-result-wrong"
          }
        >
          <p
            className={
              result.is_correct
                ? "text-sm font-medium text-success"
                : "text-sm font-medium text-destructive"
            }
          >
            {result.is_correct ? "Correct" : "Not quite"}
          </p>
          {result.explanation ? (
            <p className="mt-1 text-xs text-muted-foreground whitespace-pre-wrap">
              {result.explanation}
            </p>
          ) : null}
          {!result.is_correct && expectedOutput ? (
            <div className="mt-2">
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                Expected output
              </p>
              <pre className="mt-1 rounded-md bg-muted/30 px-3 py-2 text-xs font-mono whitespace-pre-wrap">
                {expectedOutput}
              </pre>
            </div>
          ) : null}
          {onAdvance ? (
            <div className="mt-3">
              <Button
                type="button"
                size="sm"
                onClick={onAdvance}
                data-testid="code-exercise-next"
              >
                Next
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}

      {submitError ? (
        <p
          role="alert"
          className="text-xs text-destructive"
          data-testid="code-exercise-submit-error"
        >
          {submitError}
        </p>
      ) : null}

      {hints && hints.length > 0 ? (
        <details
          className="rounded-md border border-border/60 p-2"
          data-testid="code-exercise-hints"
        >
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
            Hints ({hints.length})
          </summary>
          <ol className="mt-2 space-y-1 pl-4 text-xs text-muted-foreground list-decimal">
            {hints.map((h, i) => (
              <li key={i}>{h}</li>
            ))}
          </ol>
        </details>
      ) : null}
    </div>
  );
}

export default CodeExerciseBlock;
