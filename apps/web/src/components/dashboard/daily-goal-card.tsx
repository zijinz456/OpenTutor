"use client";

/**
 * `<DailyGoalCard>` — dashboard card showing today's XP goal progress
 * (Phase 16c Bundle B — Subagent B).
 *
 * Compact card with a horizontal progress bar + supportive copy:
 *   - default: "{earned} / {goal} XP" with bar
 *   - earned >= goal: "Daily goal met" with emerald check
 *   - new account (goal=10, earned=0): "Earn 10 XP today to start"
 *
 * Per ТЗ §11 there is no shaming language — both not-yet-met and met
 * states stay calm. Only emerald + muted/border/card tokens are used.
 */
import { useEffect, useState } from "react";
import { clsx } from "clsx";

export interface DailyGoalCardProps {
  dailyGoalXp: number;
  dailyXpEarned: number;
  className?: string;
}

/** Clamp the bar fill to [0..100]; goal=0 collapses to 0 to avoid /0. */
function fillPct(earned: number, goal: number): number {
  if (goal <= 0) return 0;
  const ratio = (earned / goal) * 100;
  if (Number.isNaN(ratio)) return 0;
  if (ratio < 0) return 0;
  if (ratio > 100) return 100;
  return ratio;
}

export function DailyGoalCard({
  dailyGoalXp,
  dailyXpEarned,
  className,
}: DailyGoalCardProps) {
  const met = dailyGoalXp > 0 && dailyXpEarned >= dailyGoalXp;
  // New-account state keys off the canonical default (goal=10, earned=0)
  // — anything else uses the regular progress copy.
  const isStarter =
    dailyGoalXp === 10 && dailyXpEarned === 0 && !met;
  const pct = fillPct(dailyXpEarned, dailyGoalXp);

  // A.7 motion polish — animate the bar from 0 → real % on first paint.
  // `displayPct` starts at 0 and flips to the real value after the
  // first effect tick. The CSS `transition-[width]` on the bar below
  // catches that delta and sweeps the fill in. Effect runs synchronously
  // inside React Testing Library's `act()` wrapper, so existing tests
  // asserting `bar.style.width === "50%"` continue to pass.
  const [displayPct, setDisplayPct] = useState(0);
  useEffect(() => {
    setDisplayPct(pct);
  }, [pct]);

  return (
    <section
      data-testid="daily-goal-card"
      aria-label="Today's XP goal"
      className={clsx(
        "rounded-2xl border border-border bg-card p-5 card-shadow",
        "flex flex-col gap-3",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-semibold text-foreground">Today&apos;s goal</p>
        {met && (
          <span
            data-testid="daily-goal-card-met"
            className="inline-flex items-center gap-1 text-xs font-medium text-emerald-500"
          >
            <span aria-hidden="true">✓</span>
            Daily goal met
          </span>
        )}
      </div>

      <p
        data-testid="daily-goal-card-progress"
        className="text-xs text-muted-foreground tabular-nums"
      >
        {isStarter
          ? "Earn 10 XP today to start"
          : `${dailyXpEarned.toLocaleString()} / ${dailyGoalXp.toLocaleString()} XP`}
      </p>

      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={dailyGoalXp}
        aria-valuenow={Math.min(dailyXpEarned, dailyGoalXp)}
        aria-label="Today's XP progress"
        className="h-2 w-full overflow-hidden rounded-full bg-emerald-500/20"
      >
        <div
          data-testid="daily-goal-card-bar"
          className="h-full rounded-full bg-emerald-500 transition-[width] duration-[var(--thm-dur-slow)] ease-[var(--thm-ease-out)]"
          style={{ width: `${displayPct}%` }}
        />
      </div>
    </section>
  );
}
