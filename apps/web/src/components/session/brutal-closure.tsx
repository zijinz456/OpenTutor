"use client";

/**
 * `<BrutalClosure>` — end-of-session screen for the Brutal Drill runner
 * (Phase 6 T5).
 *
 * Distinct tone vs `<SessionClosure>`: factual, not congratulatory.
 * MASTER §8 forbids guilt-via-streak in the ADHD daily closure; Brutal
 * flips this — the user explicitly opted into an interview-prep night
 * and wants diagnostic signal, not "Done for today. Come back when you
 * want." We surface max streak, force-retired count, and the top-3
 * weakest concepts because that's what the caller can act on tomorrow.
 *
 * Design notes
 * ------------
 * * **No "nice job" copy.** Headline is "Brutal Drill complete." —
 *   informational, no praise. Mirrors the mode's deliberate anti-soft
 *   posture; a user who just spent 22 minutes being auto-failed on
 *   timeouts does not want a pat on the head.
 * * **Force-retired count renders a diagnostic hint.** If >0 we tell the
 *   user "N cards hit 10-attempt cap — consider editing those cards"
 *   because a card looping to force-retire is almost always either
 *   (a) the learner hasn't seen the underlying concept at all or (b)
 *   the card itself is ambiguous. Either way the useful next step is
 *   review, not another drill.
 * * **Top-3 weakest concepts.** Sort `conceptFailTally` desc by count,
 *   take 3, render with counts. Cards that lacked a `concept_slug`
 *   contribute to `__unlabeled__` — we still render that bucket so a
 *   signal never silently disappears; the label is muted so it doesn't
 *   look like a concept name.
 */

import { Target } from "lucide-react";
import { Button } from "@/components/ui/button";

interface BrutalClosureProps {
  /** Total elapsed time in milliseconds. Formatted as `mm:ss`. */
  durationMs: number;
  maxStreak: number;
  masteredCount: number;
  /** Count of cards that hit the 10-attempt cap. Diagnostic hint renders
   *  when > 0. */
  forceRetiredCount: number;
  /** `concept_slug → wrong-answer count`. Top-3 extracted in render. */
  conceptFailTally: Record<string, number>;
  onBack: () => void;
  /** "Run another Brutal" — redirects with `open_brutal=true` so the
   *  dashboard picker auto-opens. */
  onRunAnother: () => void;
}

/** `mm:ss` with zero-padded minutes (so `22:00` and `02:05` both fit
 *  the same column width). Negative / NaN inputs collapse to `00:00`. */
function formatMmSs(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "00:00";
  const totalSec = Math.floor(ms / 1000);
  const mm = Math.floor(totalSec / 60);
  const ss = totalSec % 60;
  return `${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}

/** Pretty-print the synthetic `__unlabeled__` bucket; all other slugs
 *  render unchanged. Kept inline — too small to warrant its own module. */
function conceptLabel(slug: string): string {
  return slug === "__unlabeled__" ? "unlabeled" : slug;
}

export function BrutalClosure({
  durationMs,
  maxStreak,
  masteredCount,
  forceRetiredCount,
  conceptFailTally,
  onBack,
  onRunAnother,
}: BrutalClosureProps) {
  const top3 = Object.entries(conceptFailTally)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3);

  return (
    <div
      data-testid="brutal-closure"
      className="mx-auto flex max-w-md flex-col items-center gap-4 rounded-2xl bg-card p-8 text-center card-shadow"
    >
      <Target className="size-12 text-amber-500" aria-hidden="true" />
      <div className="space-y-1">
        <h1 className="text-xl font-semibold text-foreground">
          Brutal Drill complete.
        </h1>
      </div>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm tabular-nums">
        <dt className="text-muted-foreground text-right">Time</dt>
        <dd
          data-testid="brutal-closure-time"
          className="text-left font-medium text-foreground"
        >
          {formatMmSs(durationMs)}
        </dd>

        <dt className="text-muted-foreground text-right">Max streak</dt>
        <dd
          data-testid="brutal-closure-streak"
          className="text-left font-medium text-foreground"
        >
          Max streak: {maxStreak}
        </dd>

        <dt className="text-muted-foreground text-right">Mastered</dt>
        <dd
          data-testid="brutal-closure-mastered"
          className="text-left font-medium text-foreground"
        >
          {masteredCount} {masteredCount === 1 ? "card" : "cards"}
        </dd>

        <dt className="text-muted-foreground text-right">Force-retired</dt>
        <dd
          data-testid="brutal-closure-retired"
          className="text-left font-medium text-foreground"
        >
          {forceRetiredCount}
        </dd>
      </dl>

      {forceRetiredCount > 0 ? (
        <p
          data-testid="brutal-closure-retired-hint"
          className="text-xs text-muted-foreground"
        >
          {forceRetiredCount} {forceRetiredCount === 1 ? "card" : "cards"} hit
          the 10-attempt cap — consider editing those cards.
        </p>
      ) : null}

      {top3.length > 0 ? (
        <div
          data-testid="brutal-closure-weakest"
          className="w-full text-left"
        >
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1.5">
            Weakest concepts
          </p>
          <ul className="space-y-1 text-sm">
            {top3.map(([slug, count]) => (
              <li
                key={slug}
                data-testid={`brutal-closure-concept-${slug}`}
                className="flex items-center justify-between gap-3"
              >
                <span
                  className={
                    slug === "__unlabeled__"
                      ? "text-muted-foreground italic"
                      : "text-foreground"
                  }
                >
                  {conceptLabel(slug)}
                </span>
                <span className="text-muted-foreground tabular-nums">
                  {count}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="flex w-full flex-col gap-2">
        <Button
          type="button"
          onClick={onBack}
          data-testid="brutal-closure-back"
          className="w-full"
        >
          Back to dashboard
        </Button>
        <button
          type="button"
          onClick={onRunAnother}
          data-testid="brutal-closure-run-another"
          className="text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          Run another Brutal
        </button>
      </div>
    </div>
  );
}
