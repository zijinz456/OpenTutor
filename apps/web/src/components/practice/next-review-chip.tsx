"use client";

/**
 * `<NextReviewChip>` — Phase C SRS visibility chip.
 *
 * Surfaces the FSRS schedule decision after each successful submit so the
 * learner SEES that a card was scheduled forward (instead of the silent
 * "answer disappears, mystery interval grows in the DB" behaviour the
 * pre-Phase-C UI had — see `plan/phase_c_lesson_practice_recall_design.md`
 * §1 for the pain analysis).
 *
 * Self-hide rules (architect plan §5 risks):
 *   - `intervalDays <= 0` → render nothing. FSRS init failures and the
 *     "stability == 0" edge case (tracker.py:178) would otherwise produce
 *     "Returns in 0 days" which is nonsense.
 *   - Both inputs null/undefined → render nothing. A tracker exception
 *     in the backend leaves the fields null; we'd rather show silence
 *     than a half-rendered chip.
 *
 * Display rules:
 *   - With `nextReviewAt` AND `intervalDays > 0` AND interval ≤ 7d:
 *     "Returns Mon 18 May" — the weekday makes the schedule legible
 *     without the user having to count days.
 *   - Otherwise (interval > 7d OR no date): "Returns in N days".
 *
 * Pure presentational. No API calls, no state.
 */

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;
const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

const NEAR_TERM_THRESHOLD_DAYS = 7;

export interface NextReviewChipProps {
  intervalDays?: number | null;
  /** ISO 8601 datetime string (e.g. ``"2026-05-18T00:00:00Z"``). */
  nextReviewAt?: string | null;
  className?: string;
}

/** Format a Date as e.g. ``"Mon 18 May"``. Pure (no locale-specific
 *  surprises), avoids `Intl.DateTimeFormat` so the test snapshot is
 *  stable across CI environments. */
function formatWeekdayDate(date: Date): string {
  const wd = WEEKDAYS[date.getUTCDay()];
  const day = date.getUTCDate();
  const month = MONTHS[date.getUTCMonth()];
  return `${wd} ${day} ${month}`;
}

export function NextReviewChip({
  intervalDays,
  nextReviewAt,
  className,
}: NextReviewChipProps) {
  // Architect-plan §5 risk-row 3 — FSRS edge case where stability rounds
  // to 0. The chip must hide rather than print "Returns in 0 days".
  if (intervalDays === null || intervalDays === undefined || intervalDays <= 0) {
    return null;
  }

  // Near-term schedules render the weekday/date so "Returns Mon 18 May"
  // is more legible than "Returns in 14 days". Far-out (> 7 days) keeps
  // the day count — the weekday gives no extra signal at that horizon.
  let label: string;
  if (nextReviewAt && intervalDays <= NEAR_TERM_THRESHOLD_DAYS) {
    const parsed = new Date(nextReviewAt);
    if (!Number.isNaN(parsed.getTime())) {
      label = `Returns ${formatWeekdayDate(parsed)}`;
    } else {
      // Malformed date string — graceful fallback to interval.
      label = `Returns in ${intervalDays} ${intervalDays === 1 ? "day" : "days"}`;
    }
  } else {
    label = `Returns in ${intervalDays} ${intervalDays === 1 ? "day" : "days"}`;
  }

  return (
    <span
      data-testid="next-review-chip"
      className={`inline-flex items-center rounded-full border border-border/60 bg-muted/40 px-3 py-1 text-[11px] font-medium text-muted-foreground ${className ?? ""}`.trim()}
    >
      {label}
    </span>
  );
}

export default NextReviewChip;
