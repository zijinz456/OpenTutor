"use client";

/**
 * `<ExplainStep>` — Slice 3 Path B Feynman widget.
 *
 * "In your own words — what did you do?" reflection capture, persisted to
 * `localStorage` keyed by `problemId`. ТЗ §0 commits the project to
 * local-only / personal-use, so the explanation never crosses the
 * network — Slice 5 may migrate to the progress model later, the
 * widget contract (problemId in, void out) stays the same.
 *
 * Critic rulings honoured (manager-supplied):
 *   - C1: visible always, never gates Submit. Auto-focus textarea on
 *     miss as a gentle nudge; user can still ignore.
 *   - C3: starts collapsed (1-line "Explain it" pill) when the answer
 *     was correct or when no result yet. On miss, starts expanded.
 *
 * The localStorage key prefix `learndopamine:explain:` is a stable
 * contract — search the codebase before renaming. `setItem` is wrapped
 * in try/catch so a quota error / private-mode block never crashes the
 * surrounding card; the user just loses the persistence guarantee.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";

const LOCAL_STORAGE_KEY_PREFIX = "learndopamine:explain:";

export interface ExplainStepProps {
  problemId: string;
  /** Whether the user's last submission was correct. Drives initial
   *  collapsed/expanded state and the auto-focus nudge. */
  correct: boolean;
  className?: string;
}

function storageKey(problemId: string): string {
  return `${LOCAL_STORAGE_KEY_PREFIX}${problemId}`;
}

function readStored(problemId: string): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(storageKey(problemId)) ?? "";
  } catch {
    return "";
  }
}

function writeStored(problemId: string, value: string): boolean {
  if (typeof window === "undefined") return false;
  try {
    window.localStorage.setItem(storageKey(problemId), value);
    return true;
  } catch {
    return false;
  }
}

export function ExplainStep({ problemId, correct, className }: ExplainStepProps) {
  // Read existing stored value lazily — once on mount, then again whenever
  // problemId flips so the same widget instance can carry across cards.
  const [text, setText] = useState<string>(() => readStored(problemId));
  // Miss → expanded (C3 ruling). Correct or "no result yet" → collapsed.
  const [expanded, setExpanded] = useState<boolean>(!correct);
  const [savedRecently, setSavedRecently] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Sync state when the host swaps problemId (e.g., dispatch advances to a
  // new task). We re-read storage so the user's prior reflection on this
  // problem comes back if they revisit.
  useEffect(() => {
    setText(readStored(problemId));
    setExpanded(!correct);
    setSavedRecently(false);
  }, [problemId, correct]);

  // Auto-focus on miss (C1 nudge). Runs after expand, so the textarea is
  // mounted. We deliberately do NOT auto-focus on correct — that would
  // pull the user back into the reflection field after a celebratory state.
  useEffect(() => {
    if (expanded && !correct) {
      textareaRef.current?.focus();
    }
  }, [expanded, correct]);

  // Cleanup the "Saved" badge timer if the component unmounts mid-fade.
  useEffect(() => {
    return () => {
      if (savedTimer.current) clearTimeout(savedTimer.current);
    };
  }, []);

  const handleSave = useCallback(() => {
    writeStored(problemId, text);
    setSavedRecently(true);
    if (savedTimer.current) clearTimeout(savedTimer.current);
    savedTimer.current = setTimeout(() => setSavedRecently(false), 2000);
  }, [problemId, text]);

  const handleExpand = useCallback(() => setExpanded(true), []);

  return (
    <div
      className={`flex flex-col gap-2 ${className ?? ""}`.trim()}
      data-testid={`explain-step-${problemId}`}
    >
      {expanded ? (
        <>
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">
              In your own words — what did you do?
            </span>
            <textarea
              ref={textareaRef}
              data-testid={`explain-step-textarea-${problemId}`}
              className="min-h-[80px] w-full resize-y rounded-md border border-border bg-muted/30 p-2 text-xs focus:outline-none focus:ring-2 focus:ring-ring"
              placeholder="In your own words — what did you do?"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </label>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={handleSave}
              data-testid={`explain-step-save-${problemId}`}
            >
              Save
            </Button>
            {savedRecently ? (
              <span
                role="status"
                aria-live="polite"
                className="text-[11px] text-success"
                data-testid={`explain-step-saved-${problemId}`}
              >
                Saved
              </span>
            ) : null}
          </div>
        </>
      ) : (
        <button
          type="button"
          onClick={handleExpand}
          data-testid={`explain-step-expand-${problemId}`}
          className="self-start rounded-full border border-border/60 bg-muted/30 px-3 py-1 text-[11px] font-medium text-muted-foreground hover:border-primary/50"
        >
          Explain it
        </button>
      )}
    </div>
  );
}

export default ExplainStep;
