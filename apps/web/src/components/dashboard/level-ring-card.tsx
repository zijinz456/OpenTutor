/**
 * `<LevelRingCard>` — dashboard card showing tier, total XP, and a
 * circular progress ring (Phase 16c Bundle B — Subagent B).
 *
 * Compact dashboard wrapper that lives inside the "More tools" 4-card
 * gamification block. The hex prefix + tier label mirrors `<XpLevelChip>`
 * (kept inline rather than depending on it because this card uses a
 * larger layout — big XP number + SVG ring instead of a slim bar). No
 * new color tokens — emerald/muted/border/card only.
 *
 * `xpToNextLevel === 0` means the user is at the cap; we render
 * "Maxed" copy instead of an XP delta.
 */
import { clsx } from "clsx";

const LEVEL_NAMES = [
  "Bronze",
  "Silver",
  "Gold",
  "Platinum",
  "Diamond",
] as const;

export interface LevelRingCardProps {
  xpTotal: number;
  /** Full tier label, e.g. "Silver II". */
  levelTier: string;
  /** Bare level name (used to derive the hex prefix), e.g. "Silver". */
  levelName: string;
  /** 0..100 progress towards the next tier. */
  levelProgressPct: number;
  /** XP needed to hit the next tier; 0 means maxed. */
  xpToNextLevel: number;
  className?: string;
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

// SVG ring geometry — kept as constants so the JSX stays clean. The
// stroke width is intentionally small (4) so the ring reads as a thin
// halo around the XP number rather than a chunky donut.
const RING_SIZE = 96;
const RING_RADIUS = 42;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

export function LevelRingCard({
  xpTotal,
  levelTier,
  levelName,
  levelProgressPct,
  xpToNextLevel,
  className,
}: LevelRingCardProps) {
  const prefix = hexPrefix(levelName);
  const pct = clampPct(levelProgressPct);
  // Stroke offset = full circumference when 0%, 0 when 100%.
  const dashOffset = RING_CIRCUMFERENCE * (1 - pct / 100);
  const isMaxed = xpToNextLevel <= 0;

  return (
    <section
      data-testid="level-ring-card"
      aria-label="Level and XP"
      className={clsx(
        "rounded-2xl border border-border bg-card p-5 card-shadow",
        "flex flex-col gap-3",
        className,
      )}
    >
      <p
        data-testid="level-ring-card-tier"
        className="font-mono text-xs tracking-wide text-muted-foreground"
      >
        <span>{prefix}</span>
        <span className="ml-1 text-foreground">[{levelTier.toUpperCase()}]</span>
      </p>

      <div className="flex items-center gap-4">
        <svg
          data-testid="level-ring-card-progress"
          width={RING_SIZE}
          height={RING_SIZE}
          viewBox={`0 0 ${RING_SIZE} ${RING_SIZE}`}
          aria-hidden="true"
          className="shrink-0"
        >
          {/* Track — muted full-circle background. */}
          <circle
            cx={RING_SIZE / 2}
            cy={RING_SIZE / 2}
            r={RING_RADIUS}
            fill="none"
            strokeWidth={4}
            className="stroke-muted/40"
          />
          {/* Active arc — emerald, rotated -90deg so 0% starts at top. */}
          <circle
            cx={RING_SIZE / 2}
            cy={RING_SIZE / 2}
            r={RING_RADIUS}
            fill="none"
            strokeWidth={4}
            strokeLinecap="round"
            strokeDasharray={RING_CIRCUMFERENCE}
            strokeDashoffset={dashOffset}
            transform={`rotate(-90 ${RING_SIZE / 2} ${RING_SIZE / 2})`}
            className="stroke-emerald-500 transition-[stroke-dashoffset]"
          />
        </svg>

        <div className="flex flex-col gap-0.5 min-w-0">
          <p
            data-testid="level-ring-card-xp-total"
            className="text-2xl font-semibold tabular-nums text-foreground"
          >
            {xpTotal.toLocaleString()} XP
          </p>
          <p
            data-testid="level-ring-card-next"
            className="text-xs text-muted-foreground tabular-nums"
          >
            {isMaxed
              ? "Maxed"
              : `${xpToNextLevel.toLocaleString()} XP to next level`}
          </p>
        </div>
      </div>
    </section>
  );
}
