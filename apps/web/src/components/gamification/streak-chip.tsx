/**
 * `<StreakChip>` — daily streak indicator (Phase 16c Bundle C — Subagent A).
 *
 * Single allowed emoji surface per ТЗ §11: the 🔥 sits on the streak chip,
 * not anywhere else in the dashboard. When the streak is positive we tint
 * with ``--track-python`` (emerald); a zero streak renders muted with
 * encouraging copy. Freezes-left is a small sub-line; the no-freezes case
 * uses calm "keep going" copy rather than alarm.
 */
import { clsx } from "clsx";

export interface StreakChipProps {
  streakDays: number;
  freezesLeft: number;
}

export function StreakChip({ streakDays, freezesLeft }: StreakChipProps) {
  const active = streakDays > 0;
  const noFreezes = freezesLeft === 0;

  return (
    <section
      data-testid="streak-chip"
      aria-label="Daily streak"
      className={clsx(
        "rounded-2xl border p-4 card-shadow",
        "border-[var(--border-subtle,rgba(255,255,255,0.08))]",
        "bg-[var(--bg-surface,rgba(255,255,255,0.02))]",
      )}
    >
      <div className="flex items-center gap-3">
        <span
          aria-hidden="true"
          className={clsx(
            "text-lg leading-none",
            active ? "opacity-100" : "opacity-50",
          )}
        >
          🔥
        </span>
        <p
          data-testid="streak-chip-days"
          className={clsx(
            "text-sm font-semibold tabular-nums",
            active
              ? "text-[var(--track-python,#34D399)]"
              : "text-[var(--text-secondary)]",
          )}
        >
          {active ? `Streak ${streakDays} days` : "No streak yet — start today"}
        </p>
      </div>

      <p
        data-testid="streak-chip-freezes"
        className="mt-1.5 pl-7 text-xs text-[var(--text-secondary)] tabular-nums"
      >
        {noFreezes
          ? "No freezes this week. Keep going."
          : `${freezesLeft} ${freezesLeft === 1 ? "freeze" : "freezes"} left`}
      </p>
    </section>
  );
}
