/**
 * `<ProgressBar>` — tiny horizontal progress indicator reused by
 * `<PathCard>` and `<RoomListItem>` (Phase 16a T4).
 *
 * Deliberately minimal — just label + count + bar. Kept presentational
 * (no client state) so it composes cleanly inside list items.
 */

interface ProgressBarProps {
  label: string;
  current: number;
  total: number;
  /** Override fill color — defaults to the brand primary. */
  fillClassName?: string;
  testId?: string;
}

export function ProgressBar({
  label,
  current,
  total,
  fillClassName = "bg-primary",
  testId,
}: ProgressBarProps) {
  // Divide-by-zero guard: when total=0 we render an empty track rather
  // than NaN%. An empty room/path is still informative in the UI —
  // "0/0" tells the user the slot is present but unpopulated.
  const pct = total > 0 ? Math.min(100, Math.round((current / total) * 100)) : 0;

  return (
    <div className="flex flex-col gap-1" data-testid={testId}>
      <div className="flex items-baseline justify-between text-[11px] text-muted-foreground">
        <span>{label}</span>
        <span>
          {current}/{total}
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={`h-full transition-[width] ${fillClassName}`}
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={current}
          aria-valuemin={0}
          aria-valuemax={total}
          aria-label={`${label} progress`}
        />
      </div>
    </div>
  );
}
