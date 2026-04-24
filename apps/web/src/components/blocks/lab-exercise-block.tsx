"use client";

/**
 * <LabExerciseBlock>
 *
 * Hacking Labs Phase 12 T3 (plan: plan/hacking_labs_phase12.md).
 *
 * Renders a single web-security lab card: task description + an "Open Lab"
 * deep-link to the sandbox target (Juice Shop at http://localhost:3100 by
 * default, per §34.6 T1), and three proof-of-solve inputs (payload used,
 * flag/evidence observed, optional localhost screenshot URL).
 *
 * Structural parallel to <CodeExerciseBlock>:
 *   - Same reset-on-problemId useEffect pattern (drop previous card state)
 *   - Same isLocked = submitting || result !== null guard
 *   - Same green/red success/failure result pane layout
 *   - Same collapsible <details> hints drawer
 *
 * Deliberate divergences:
 *   - No Monaco / no Run step — grading is server-side rubric only.
 *   - No keyboard shortcuts — the user spends their time in a separate
 *     browser tab attacking the lab; shortcuts in this pane are noise.
 *   - Safety banner is UNCONDITIONAL — not a prop toggle. Every lab card
 *     must display "attack only the local sandbox" framing.
 *   - The Open Lab link uses target="_blank" rel="noopener noreferrer" so
 *     the sandbox can never access window.opener (even though it's
 *     localhost — defence-in-depth against a future cross-host scenario).
 *   - screenshot_url client-side regex mirrors the backend validator in
 *     apps/api/schemas/quiz.py:_LOCALHOST_URL_RE exactly. If the two ever
 *     drift, the client just shows an inline error while the backend still
 *     enforces — no security downgrade, only UX worsening.
 *
 * `expected_output` / `verification_rubric` from the backend problem row are
 * intentionally NOT props here. The grading rubric stays server-side; the
 * client never sees the "correct" answer before the user submits.
 */

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ExplainStep } from "@/components/practice/explain-step";
import { MissBanner } from "@/components/practice/miss-banner";

/** Localhost URL regex — mirrors apps/api/schemas/quiz.py:_LOCALHOST_URL_RE. */
const LOCALHOST_URL_RE = /^http:\/\/localhost:\d+(\/|$)/;

export interface LabExerciseSubmitPayload {
  payload_used: string;
  flag_or_evidence: string;
  screenshot_url?: string;
}

export interface LabExerciseSubmitResult {
  is_correct: boolean;
  explanation?: string;
  /** Optional 0–1 confidence from the grader; rendered as a subtle note. */
  confidence?: number;
}

export interface LabExerciseBlockProps {
  problemId: string;
  questionText: string;
  targetUrl: string;
  category?: string;
  difficulty?: "easy" | "medium" | "hard";
  hints?: string[];
  /** Optional course/track id for the "Add to review" link in the
   *  miss banner (Slice 3 Path B). */
  courseId?: string;
  onSubmit: (
    payload: LabExerciseSubmitPayload,
  ) => Promise<LabExerciseSubmitResult>;
  onAdvance?: () => void;
}

export function LabExerciseBlock({
  problemId,
  questionText,
  targetUrl,
  category,
  difficulty,
  hints,
  courseId,
  onSubmit,
  onAdvance,
}: LabExerciseBlockProps) {
  const [payloadUsed, setPayloadUsed] = useState("");
  const [flagOrEvidence, setFlagOrEvidence] = useState("");
  const [screenshotUrl, setScreenshotUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<LabExerciseSubmitResult | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Reset local state when parent swaps to a different lab. Mirrors
  // <CodeExerciseBlock>'s reset effect — prevents stale proof bleeding
  // across cards during dispatch navigation.
  useEffect(() => {
    setPayloadUsed("");
    setFlagOrEvidence("");
    setScreenshotUrl("");
    setResult(null);
    setSubmitError(null);
  }, [problemId]);

  // Validate screenshot URL on every keystroke — we block Submit rather
  // than lazy-check on submit click so the user sees the issue immediately.
  // Empty string is always OK (field is optional). Matches backend
  // precondition: non-empty MUST match the localhost regex.
  const screenshotUrlInvalid =
    screenshotUrl.trim().length > 0 && !LOCALHOST_URL_RE.test(screenshotUrl.trim());

  const requiredMissing =
    payloadUsed.trim().length === 0 || flagOrEvidence.trim().length === 0;

  const isLocked = submitting || result !== null;
  const submitDisabled = isLocked || requiredMissing || screenshotUrlInvalid;

  const handleSubmit = useCallback(async () => {
    if (submitDisabled) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      // Trim whitespace so the payload sent to the grader matches what the
      // user actually typed visually. `screenshot_url` is omitted (undefined)
      // when empty — backend treats null/missing/"" all as "no screenshot".
      const trimmedScreenshot = screenshotUrl.trim();
      const res = await onSubmit({
        payload_used: payloadUsed.trim(),
        flag_or_evidence: flagOrEvidence.trim(),
        screenshot_url: trimmedScreenshot.length > 0 ? trimmedScreenshot : undefined,
      });
      setResult(res);
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : "Submit failed — try again",
      );
    } finally {
      setSubmitting(false);
    }
  }, [flagOrEvidence, onSubmit, payloadUsed, screenshotUrl, submitDisabled]);

  const difficultyVariant =
    difficulty === "hard"
      ? "bg-destructive/10 text-destructive"
      : difficulty === "medium"
        ? "bg-warning/10 text-warning"
        : "bg-success/10 text-success";

  return (
    <div
      role="form"
      aria-label="Lab exercise"
      className="flex flex-col gap-3 p-4"
      data-testid="lab-exercise-block"
    >
      {/* UNCONDITIONAL safety banner. Orange/destructive-toned. Every lab
          card displays this — it's not a prop. */}
      <div
        role="note"
        className="rounded-md border border-warning/40 bg-warning/10 p-3 text-xs text-warning"
        data-testid="lab-exercise-safety-banner"
      >
        <strong className="font-semibold">⚠ Attack ONLY the local sandbox target shown below.</strong>{" "}
        Never use these techniques against external systems you don&apos;t own.
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant="outline" className="text-[10px]">
          Hacking Lab
        </Badge>
        {category ? (
          <Badge
            variant="outline"
            className="text-[10px]"
            data-testid="lab-exercise-category"
          >
            {category}
          </Badge>
        ) : null}
        {difficulty ? (
          <Badge
            variant="outline"
            className={`text-[10px] ${difficultyVariant}`}
            data-testid="lab-exercise-difficulty"
          >
            {difficulty}
          </Badge>
        ) : null}
      </div>

      <p
        id={`lab-exercise-prompt-${problemId}`}
        className="text-base font-medium leading-relaxed whitespace-pre-wrap"
        data-testid="lab-exercise-prompt"
      >
        {questionText}
      </p>

      <div className="flex flex-col gap-1">
        <Button
          asChild
          type="button"
          size="sm"
          variant="outline"
          className="self-start"
        >
          <a
            href={targetUrl}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="lab-exercise-open-lab"
            aria-label="Open lab target in new tab"
          >
            Open Lab ↗
          </a>
        </Button>
        <span
          className="text-[10px] text-muted-foreground font-mono break-all"
          data-testid="lab-exercise-target-url"
        >
          {targetUrl}
        </span>
      </div>

      <div className="flex flex-col gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted-foreground">
            Payload / attack used <span className="text-destructive">*</span>
          </span>
          <textarea
            data-testid="lab-exercise-payload"
            className="w-full rounded-md border border-border bg-muted/30 font-mono text-xs p-2 min-h-[80px] resize-y focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
            placeholder="e.g. <script>alert(1)</script>"
            value={payloadUsed}
            onChange={(e) => setPayloadUsed(e.target.value)}
            disabled={isLocked}
            spellCheck={false}
            aria-required="true"
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted-foreground">
            Flag or evidence observed <span className="text-destructive">*</span>
          </span>
          <textarea
            data-testid="lab-exercise-flag"
            className="w-full rounded-md border border-border bg-muted/30 font-mono text-xs p-2 min-h-[80px] resize-y focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
            placeholder="e.g. 'Alert fired on search results page, reflected XSS confirmed'"
            value={flagOrEvidence}
            onChange={(e) => setFlagOrEvidence(e.target.value)}
            disabled={isLocked}
            spellCheck={false}
            aria-required="true"
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted-foreground">
            Screenshot URL (optional — localhost only)
          </span>
          <input
            type="url"
            data-testid="lab-exercise-screenshot"
            className="w-full rounded-md border border-border bg-muted/30 font-mono text-xs p-2 focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
            placeholder="http://localhost:3100/path/to/screenshot.png"
            value={screenshotUrl}
            onChange={(e) => setScreenshotUrl(e.target.value)}
            disabled={isLocked}
            spellCheck={false}
            aria-invalid={screenshotUrlInvalid || undefined}
          />
          {screenshotUrlInvalid ? (
            <span
              role="alert"
              className="text-xs text-destructive"
              data-testid="lab-exercise-screenshot-error"
            >
              Must start with http://localhost:&lt;port&gt; (screenshots stay on your machine).
            </span>
          ) : null}
        </label>
      </div>

      <div className="flex items-center gap-2">
        <Button
          type="button"
          size="sm"
          disabled={submitDisabled}
          onClick={() => void handleSubmit()}
          aria-label="Submit lab proof"
          data-testid="lab-exercise-submit"
        >
          {submitting ? "Grading..." : "Submit proof"}
        </Button>
      </div>

      {result !== null ? (
        result.is_correct ? (
          <div
            role="status"
            aria-live="polite"
            className="rounded-md border border-success/40 bg-success/10 p-3"
            data-testid="lab-exercise-result-correct"
          >
            <div className="flex items-center gap-2">
              <p className="text-sm font-medium text-success">Solved</p>
              {typeof result.confidence === "number" ? (
                <Badge
                  variant="outline"
                  className="text-[10px]"
                  data-testid="lab-exercise-confidence"
                  title="Grader's self-reported confidence"
                >
                  confidence {Math.round(result.confidence * 100)}%
                </Badge>
              ) : null}
            </div>
            {result.explanation ? (
              <p className="mt-1 text-xs text-muted-foreground whitespace-pre-wrap">
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
                  data-testid="lab-exercise-next"
                >
                  Next
                </Button>
              </div>
            ) : null}
          </div>
        ) : (
          <div data-testid="lab-exercise-result-wrong">
            <MissBanner
              problemId={problemId}
              courseId={courseId}
              revealedAnswer={null}
            >
              {typeof result.confidence === "number" ? (
                <Badge
                  variant="outline"
                  className="text-[10px]"
                  data-testid="lab-exercise-confidence"
                  title="Grader's self-reported confidence"
                >
                  confidence {Math.round(result.confidence * 100)}%
                </Badge>
              ) : null}
              {result.explanation ? (
                <p className="text-xs text-muted-foreground whitespace-pre-wrap">
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
                  data-testid="lab-exercise-next"
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
          data-testid="lab-exercise-submit-error"
        >
          {submitError}
        </p>
      ) : null}

      {hints && hints.length > 0 ? (
        <details
          className="rounded-md border border-border/60 p-2"
          data-testid="lab-exercise-hints"
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

export default LabExerciseBlock;
