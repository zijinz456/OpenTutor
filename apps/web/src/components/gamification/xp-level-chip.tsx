/**
 * `<XpLevelChip>` — compact tier + XP + progress display
 * (Phase 16c Bundle C — Subagent A).
 *
 * Renders the hex-prefix tier badge per ТЗ §8 (`0x1 [SILVER II]`), total XP,
 * and a slim progress bar. Optionally surfaces a "Today: X / Y XP" sub-line
 * when the daily-goal props are supplied.
 *
 * No new colors are introduced — fill uses ``--accent-primary`` (emerald)
 * and the track uses ``--surface-pressed``, both already defined globally.
 */
import { clsx } from "clsx";

const LEVEL_NAMES = [
  "Bronze",
  "Silver",
  "Gold",
  "Platinum",
  "Diamond",
] as const;

export interface XpLevelChipProps {
  xpTotal: number;
  /** Full tier label, e.g. "Silver II". */
  levelTier: string;
  /** Bare level name (used to derive the hex prefix), e.g. "Silver". */
  levelName: string;
  /** 0..100 progress towards the next tier. */
  levelProgressPct: number;
  /** When provided alongside `dailyXpEarned`, the daily sub-line is shown. */
  dailyGoalXp?: number;
  dailyXpEarned?: number;
}

/** Map a level name to its 1-indexed hex prefix; unknowns get `0x?`. */
function hexPrefix(levelName: string): string {
  const idx = LEVEL_NAMES.findIndex(
    (n) => n.toLowerCase() === levelName.toLowerCase(),
  );
  return idx === -1 ? "0x?" : `0x${idx + 1}`;
}

/** Clamp a percentage into the renderable 0..100 range. */
function clampPct(pct: number): number {
  if (Number.isNaN(pct)) return 0;
  if (pct < 0) return 0;
  if (pct > 100) return 100;
  return pct;
}

export function XpLevelChip({
  xpTotal,
  levelTier,
  levelName,
  levelProgressPct,
  dailyGoalXp,
  dailyXpEarned,
}: XpLevelChipProps) {
  const prefix = hexPrefix(levelName);
  const pct = clampPct(levelProgressPct);
  const hasDaily =
    typeof dailyGoalXp === "number" &&
    dailyGoalXp > 0 &&
    typeof dailyXpEarned === "number";

  return (
    <section
      data-testid="xp-level-chip"
      aria-label="XP and level"
      className={clsx(
        "rounded-2xl border p-4 card-shadow",
        "border-[var(--border-subtle,rgba(255,255,255,0.08))]",
        "bg-[var(--bg-surface,rgba(255,255,255,0.02))]",
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <span
          data-testid="xp-level-chip-tier"
          className="font-mono text-xs tracking-wide text-[var(--text-secondary)]"
        >
          <span>{prefix}</span>
          <span className="ml-1 text-[var(--text-primary)]">
            [{levelTier.toUpperCase()}]
          </span>
        </span>
        <span className="text-sm font-semibold tabular-nums text-[var(--text-primary)]">
          {xpTotal.toLocaleString()} XP
        </span>
      </div>

      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-label={`${levelTier} progress`}
        className="mt-3 h-2 w-full overflow-hidden rounded-full bg-[var(--surface-pressed,rgba(255,255,255,0.06))]"
      >
        <div
          data-testid="xp-level-chip-bar"
          className="h-full rounded-full bg-[var(--accent-primary,#34D399)] transition-[width]"
          style={{ width: `${pct}%` }}
        />
      </div>

      {hasDaily && (
        <p
          data-testid="xp-level-chip-daily"
          className="mt-2 text-xs text-[var(--text-secondary)] tabular-nums"
        >
          Today: {dailyXpEarned} / {dailyGoalXp} XP
        </p>
      )}
    </section>
  );
}
