"use client";

/**
 * Rubric panel — renders the grader's 4-dimension scores for one turn
 * (Phase 5 T6d).
 *
 * Dimension labels are driven by the keys the grader emits (`Situation /
 * Task / Action / Result` for behavioral, `Correctness / Depth / Tradeoff
 * / Clarity` for technical + code_defense). Mixed sessions send whichever
 * shape matches the generated question, so we don't hard-code names here.
 *
 * Score range is 1..5. Bar width = `score / 5 * 100%`. Colour scales
 * three tiers for at-a-glance ADHD signal (red 1-2, amber 3, emerald 4-5)
 * — no fine-grain gradient because the grader only has 5 buckets and the
 * user already sees the numeric score.
 */

import type { RubricScores } from "@/lib/api/interview";

interface Props {
  rubric: RubricScores;
  turnNumber: number;
}

/** Bucket a 1-5 score into a colour-class tuple (bar fill + text). */
function scoreTier(score: number): { bar: string; text: string; label: string } {
  if (score <= 2) {
    return {
      bar: "bg-red-500",
      text: "text-red-700",
      label: "weak",
    };
  }
  if (score === 3) {
    return {
      bar: "bg-amber-500",
      text: "text-amber-700",
      label: "ok",
    };
  }
  return {
    bar: "bg-emerald-500",
    text: "text-emerald-700",
    label: "strong",
  };
}

export function RubricPanel({ rubric, turnNumber }: Props) {
  const entries = Object.entries(rubric.dimensions);

  return (
    <div
      data-testid="rubric-panel"
      data-turn-number={turnNumber}
      className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4"
    >
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-foreground">
          Turn {turnNumber} rubric
        </h3>
        <span className="text-xs text-muted-foreground">1 = weak · 5 = strong</span>
      </div>

      <div className="flex flex-col gap-3">
        {entries.map(([dim, { score, feedback }]) => {
          const tier = scoreTier(score);
          const pct = Math.max(0, Math.min(5, score)) * 20;
          return (
            <div
              key={dim}
              data-testid={`rubric-dim-${dim}`}
              className="flex flex-col gap-1"
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-foreground">
                  {dim}
                </span>
                <span
                  className={`text-sm font-semibold ${tier.text}`}
                  data-testid={`rubric-dim-${dim}-score`}
                >
                  {score} / 5
                </span>
              </div>
              <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
                <div
                  data-testid={`rubric-dim-${dim}-bar`}
                  className={`h-full ${tier.bar} transition-[width] duration-300`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              {feedback && (
                <p
                  className="text-xs text-muted-foreground"
                  data-testid={`rubric-dim-${dim}-feedback`}
                >
                  {feedback}
                </p>
              )}
            </div>
          );
        })}
      </div>

      {rubric.feedback_short && (
        <div
          data-testid="rubric-feedback-short"
          className="mt-1 rounded-md bg-muted px-3 py-2 text-sm text-foreground"
        >
          {rubric.feedback_short}
        </div>
      )}
    </div>
  );
}

export default RubricPanel;
