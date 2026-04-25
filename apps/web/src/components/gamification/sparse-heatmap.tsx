"use client";

/**
 * `<SparseHeatmap>` — GitHub-style 365-day XP heatmap (Phase 16c Bundle C).
 *
 * Input is sparse: only days with non-zero XP are passed in. We expand to
 * a dense 365-day window (today inclusive, going back 364 days) and fill
 * missing dates with `xp = 0`. Layout is 7 rows (days of week) × 53
 * columns (weeks); the bottom-right cell is "today".
 *
 * Color palette is restricted to the existing emerald scale (the
 * `--track-python` token from §8) plus muted background. We use Tailwind
 * utility classes that map to the in-repo tokens — no new colors, no
 * custom CSS. Per ТЗ §11 rule 11/12 there is no flash, shake, toast,
 * confetti, or sound when tiles render.
 *
 * The empty all-zero state renders as a calm muted grid (null state).
 */

import { useMemo } from "react";

export interface SparseHeatmapTile {
  /** ISO date string (`YYYY-MM-DD`) in UTC. */
  date: string;
  /** XP earned on that date (>= 0). */
  xp: number;
}

export interface SparseHeatmapProps {
  /** Sparse list of non-zero days. Order does not matter. */
  tiles: SparseHeatmapTile[];
  /**
   * Optional pinned "today" in UTC (`YYYY-MM-DD`). Defaults to the current
   * UTC date — exposed so tests get deterministic windows.
   */
  todayUtc?: string;
}

/** Total days rendered in the heatmap (matches GitHub's ~52w window). */
const WINDOW_DAYS = 365;
const ROWS = 7;
const COLS = 53;

/** Format a `Date` as `YYYY-MM-DD` in UTC. */
function toUtcIso(date: Date): string {
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/** Parse `YYYY-MM-DD` into a UTC midnight `Date`. */
function parseUtcIso(iso: string): Date {
  const [y, m, d] = iso.split("-").map((s) => Number.parseInt(s, 10));
  return new Date(Date.UTC(y, (m ?? 1) - 1, d ?? 1));
}

/**
 * Map an XP count to a Tailwind class. We use emerald for non-zero days
 * (matches the `--track-python` token from §8) and a muted swatch for 0.
 * Buckets: 0, 1–9, 10–29, 30+. The thresholds are intentionally low —
 * one short drill should already nudge the tile out of the muted state
 * so the day reads as "you did something".
 */
function bucketClass(xp: number): string {
  if (xp <= 0) return "bg-muted/30";
  if (xp < 10) return "bg-emerald-500/20";
  if (xp < 30) return "bg-emerald-500/50";
  return "bg-emerald-500";
}

interface DenseTile {
  date: string;
  xp: number;
}

/**
 * Build the dense 365-day series that ends at `todayIso` (inclusive).
 * Missing dates are filled with `xp = 0` so the grid never has gaps.
 */
function buildDenseWindow(
  tiles: SparseHeatmapTile[],
  todayIso: string,
): DenseTile[] {
  const sparseMap = new Map<string, number>();
  for (const t of tiles) {
    // Last write wins if a date is duplicated — defensive, the API
    // shouldn't emit duplicates but the widget must not crash on them.
    sparseMap.set(t.date, t.xp);
  }
  const today = parseUtcIso(todayIso);
  const out: DenseTile[] = [];
  for (let offset = WINDOW_DAYS - 1; offset >= 0; offset -= 1) {
    const d = new Date(today);
    d.setUTCDate(d.getUTCDate() - offset);
    const iso = toUtcIso(d);
    out.push({ date: iso, xp: sparseMap.get(iso) ?? 0 });
  }
  return out;
}

export function SparseHeatmap({ tiles, todayUtc }: SparseHeatmapProps) {
  const todayIso = todayUtc ?? toUtcIso(new Date());

  const dense = useMemo(
    () => buildDenseWindow(tiles, todayIso),
    [tiles, todayIso],
  );

  // Right-pad to ROWS*COLS so the CSS grid is rectangular even though
  // 7 × 53 = 371 > 365. The leading 6 cells become inert spacers; we
  // render them as muted with no testid, no tooltip, and aria-hidden so
  // screen readers ignore them.
  const leadingPad = ROWS * COLS - dense.length;

  return (
    <div
      data-testid="sparse-heatmap"
      role="img"
      aria-label="Activity over the last 365 days"
      className="w-full overflow-hidden"
    >
      <div
        className="grid gap-[2px]"
        style={{
          gridTemplateColumns: `repeat(${COLS}, minmax(0, 1fr))`,
          gridTemplateRows: `repeat(${ROWS}, minmax(0, 1fr))`,
          gridAutoFlow: "column",
        }}
      >
        {Array.from({ length: leadingPad }).map((_, i) => (
          <span
            key={`pad-${i}`}
            aria-hidden="true"
            className="aspect-square rounded-[2px] bg-muted/30"
          />
        ))}
        {dense.map((tile) => {
          const cls = bucketClass(tile.xp);
          // Only attach a testid for non-zero days — keeps the DOM lean
          // (test runs against ~365 cells already).
          const isActive = tile.xp > 0;
          return (
            <span
              key={tile.date}
              data-testid={
                isActive ? `heatmap-tile-${tile.date}` : undefined
              }
              data-xp={tile.xp}
              title={`${tile.date}: ${tile.xp} XP`}
              className={`aspect-square rounded-[2px] ${cls}`}
            />
          );
        })}
      </div>
    </div>
  );
}
