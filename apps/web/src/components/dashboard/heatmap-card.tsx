/**
 * `<HeatmapCard>` — dashboard card wrapping the 365-day XP heatmap
 * (Phase 16c Bundle B — Subagent B).
 *
 * Pure composition: header label "Last 365 days" + a small "today"
 * caption + the existing `<SparseHeatmap>`. The card is meant to span
 * the full width of the 4-card gamification block, so the heatmap grid
 * has room to breathe.
 */
import { clsx } from "clsx";
import {
  SparseHeatmap,
  type SparseHeatmapTile,
} from "@/components/gamification/sparse-heatmap";

export interface HeatmapCardProps {
  tiles: SparseHeatmapTile[];
  /** Optional pinned today (UTC `YYYY-MM-DD`) — passed through to the grid. */
  todayUtc?: string;
  className?: string;
}

export function HeatmapCard({ tiles, todayUtc, className }: HeatmapCardProps) {
  return (
    <section
      data-testid="heatmap-card"
      aria-label="Activity heatmap"
      className={clsx(
        "rounded-2xl border border-border bg-card p-5 card-shadow",
        "flex flex-col gap-3",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-semibold text-foreground">Last 365 days</p>
        <p className="text-xs text-muted-foreground">today is bottom-right</p>
      </div>
      <div data-testid="heatmap-card-grid">
        <SparseHeatmap tiles={tiles} todayUtc={todayUtc} />
      </div>
    </section>
  );
}
