/**
 * `<MissionProgressFooter>` — Slice 2 sticky mission-page footer.
 *
 * Three-column strip: Prev · Progress · Next. ТЗ §10:
 *   - Numbers bare: "58% · 12 min" (tabular-nums).
 *   - No "→" glyph in button copy — the arrow lucide icon is decoration,
 *     paired with a word label for accessibility.
 *
 * `eta_minutes` is optional: when null, the center shows just the
 * percentage. `canPrev` / `canNext` flip from the parent based on
 * `currentIdx` relative to the task list bounds — footer doesn't
 * need to know which task is current, just the pos in the range.
 */

import { ArrowLeft, ArrowRight } from "lucide-react";

export interface MissionProgressFooterProps {
  progressPct: number;
  etaMinutes: number | null;
  canPrev: boolean;
  canNext: boolean;
  onPrev: () => void;
  onNext: () => void;
}

export function MissionProgressFooter({
  progressPct,
  etaMinutes,
  canPrev,
  canNext,
  onPrev,
  onNext,
}: MissionProgressFooterProps) {
  return (
    <footer
      data-testid="mission-progress-footer"
      className="fixed bottom-0 inset-x-0 z-40 border-t border-[var(--border-subtle,rgba(255,255,255,0.06))] bg-[var(--bg-surface,hsl(var(--card)))] h-12 flex items-center"
    >
      <div className="mx-auto max-w-7xl w-full px-4 flex items-center justify-between gap-4 text-sm">
        <button
          type="button"
          data-testid="mission-progress-footer-prev"
          disabled={!canPrev}
          onClick={onPrev}
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[var(--text-secondary,hsl(var(--muted-foreground)))] hover:text-[var(--text-primary,hsl(var(--foreground)))] disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <ArrowLeft aria-hidden="true" className="size-4" />
          Prev task
        </button>

        <div
          data-testid="mission-progress-footer-progress"
          className="text-[var(--text-secondary,hsl(var(--muted-foreground)))] tabular-nums"
        >
          <span className="text-[var(--text-primary,hsl(var(--foreground)))] font-medium">
            {progressPct}%
          </span>
          {etaMinutes !== null ? (
            <>
              <span aria-hidden="true" className="mx-2">
                ·
              </span>
              <span>{etaMinutes} min</span>
            </>
          ) : null}
        </div>

        <button
          type="button"
          data-testid="mission-progress-footer-next"
          disabled={!canNext}
          onClick={onNext}
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[var(--text-secondary,hsl(var(--muted-foreground)))] hover:text-[var(--text-primary,hsl(var(--foreground)))] disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Next task
          <ArrowRight aria-hidden="true" className="size-4" />
        </button>
      </div>
    </footer>
  );
}
