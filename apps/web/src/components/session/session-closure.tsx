"use client";

/**
 * `<SessionClosure>` — the quick-finish screen for the ADHD daily flow
 * (Phase 13 T5, MASTER §8).
 *
 * Intentionally stripped of "keep going" language. MASTER §8 NO-shame
 * list explicitly bans streaks, "you've only done X today", percentage
 * progress bars hinting at unfinished work, and any "tomorrow's target"
 * framing. This screen is the moment the user is allowed to feel done.
 *
 * The single secondary "Do 1 more?" affordance is a *gift*, not a nudge
 * — the primary CTA is "Back to dashboard" and it renders first
 * (top-to-bottom reading order) so that's the default path.
 */

import { CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";

interface SessionClosureProps {
  correct: number;
  total: number;
  onBack: () => void;
  /** Optional — pass `undefined` to hide the "Do 1 more?" affordance
   *  entirely (e.g. when the backend reported `nothing_due` after an
   *  earlier size-1 session and there's genuinely nothing more to
   *  serve). */
  onDoOneMore?: () => void;
}

export function SessionClosure({
  correct,
  total,
  onBack,
  onDoOneMore,
}: SessionClosureProps) {
  const statLine =
    total === 0
      ? "Nothing due today."
      : `${total} card${total === 1 ? "" : "s"} reviewed · ${correct} remembered`;

  return (
    <div
      data-testid="session-closure"
      className="mx-auto flex max-w-md flex-col items-center gap-4 rounded-2xl bg-card p-8 text-center card-shadow"
    >
      <CheckCircle2 className="size-14 text-brand" aria-hidden="true" />
      <div className="space-y-1">
        <h1 className="text-xl font-semibold text-foreground">
          Done for today.
        </h1>
        <p className="text-sm text-muted-foreground">
          Come back when you want.
        </p>
      </div>
      <p
        className="text-xs text-muted-foreground tabular-nums"
        data-testid="session-closure-stats"
      >
        {statLine}
      </p>
      <div className="flex flex-col gap-2 w-full">
        <Button
          type="button"
          onClick={onBack}
          data-testid="session-closure-back"
          className="w-full"
        >
          Back to dashboard
        </Button>
        {onDoOneMore ? (
          <button
            type="button"
            onClick={onDoOneMore}
            data-testid="session-closure-one-more"
            className="text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            Do 1 more?
          </button>
        ) : null}
      </div>
    </div>
  );
}
