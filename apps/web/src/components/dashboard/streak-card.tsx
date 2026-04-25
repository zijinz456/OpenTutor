/**
 * `<StreakCard>` — dashboard card showing the current streak +
 * remaining freezes (Phase 16c Bundle B — Subagent B).
 *
 * Lives inside the More-tools 4-card gamification block. Reuses the
 * 🔥 emoji surface from `<StreakChip>` but uses the larger card layout
 * (big streak number + supportive sub-line). New-account state shows
 * "Start a streak today" — no shaming copy.
 */
import { clsx } from "clsx";

export interface StreakCardProps {
  streakDays: number;
  freezesLeft: number;
  className?: string;
}

export function StreakCard({
  streakDays,
  freezesLeft,
  className,
}: StreakCardProps) {
  const active = streakDays > 0;

  // Sub-line picks one of three calm copies:
  //   - active streak + freezes left → count freezes
  //   - active streak + no freezes  → "No freezes left"
  //   - no streak yet                → "Start a streak today"
  let subline: string;
  if (!active) {
    subline = "Start a streak today";
  } else if (freezesLeft <= 0) {
    subline = "No freezes left";
  } else {
    subline = `${freezesLeft} ${
      freezesLeft === 1 ? "freeze" : "freezes"
    } left this week`;
  }

  return (
    <section
      data-testid="streak-card"
      aria-label="Daily streak"
      className={clsx(
        "rounded-2xl border border-border bg-card p-5 card-shadow",
        "flex flex-col gap-2",
        className,
      )}
    >
      <div className="flex items-center gap-3">
        <span
          aria-hidden="true"
          className={clsx(
            "text-2xl leading-none",
            active ? "opacity-100" : "opacity-50",
          )}
        >
          🔥
        </span>
        <p
          data-testid="streak-card-days"
          className={clsx(
            "text-xl font-semibold tabular-nums",
            active ? "text-emerald-500" : "text-muted-foreground",
          )}
        >
          {active
            ? `Streak ${streakDays} ${streakDays === 1 ? "day" : "days"}`
            : "No streak yet"}
        </p>
      </div>
      <p
        data-testid="streak-card-freezes"
        className="text-xs text-muted-foreground tabular-nums pl-9"
      >
        {subline}
      </p>
    </section>
  );
}
