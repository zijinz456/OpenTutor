"use client";

/**
 * `<DrillCoursesPill>` — dashboard entry for the practice-first drills
 * surface (Phase 16c T21).
 *
 * Mirrors `<LearningPathsPill>` visually but points at `/courses`. Fetches
 * the course list on mount and shows aggregate module count. Panic-mode
 * hides via `data-panic-hide`.
 *
 * TODO(ТЗ §3 Slice 1 + §8): Slice 1 (Dashboard Convergence) will replace
 * this pill — either folded into `<TrackProgressRow>` or collapsed into
 * the `<details>` block. Once Slice 1 lands, revisit whether the pill
 * survives; if so, swap the hardcoded sky-* Tailwind colors for the §8
 * CSS tokens (`var(--track-python)` / `var(--bg-surface)` / etc.). Left
 * as-is for now because rewriting tokens right before a widget replacement
 * is wasted churn.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import { Code2 } from "lucide-react";
import { listDrillCourses, type DrillCourseOut } from "@/lib/api";

export function DrillCoursesPill() {
  const [data, setData] = useState<DrillCourseOut[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listDrillCourses()
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load drills");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const courseCount = data?.length ?? 0;
  const moduleTotal =
    data?.reduce((sum, c) => sum + (c.module_count ?? 0), 0) ?? 0;
  // Phase 16c B2: show aggregate per-user progress. We render
  // "пройдено X / Y" ADHD-safely — not "X з Y" (which reads like a
  // deficit framing). When Y is zero we fall back to the module-count
  // copy; a course with no drills shouldn't advertise "0 / 0" progress.
  const drillTotal =
    data?.reduce((sum, c) => sum + (c.drill_count ?? 0), 0) ?? 0;
  const passedTotal =
    data?.reduce((sum, c) => sum + (c.passed_count ?? 0), 0) ?? 0;

  return (
    <section
      aria-label="Drill courses"
      data-testid="drill-courses-pill"
      data-panic-hide
      className="rounded-2xl border border-sky-500/30 bg-sky-500/5 p-5 card-shadow"
    >
      <div className="flex items-start gap-3">
        <Code2 className="size-5 shrink-0 text-sky-600 mt-0.5" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-foreground">
            Зломи та дрилі
          </p>

          {loading && (
            <div
              data-testid="drill-courses-pill-skeleton"
              className="mt-2 h-3 w-40 rounded bg-muted/50 animate-pulse"
            />
          )}

          {!loading && error && (
            <p
              data-testid="drill-courses-pill-error"
              className="mt-1 text-xs text-muted-foreground"
            >
              {error}
            </p>
          )}

          {!loading && !error && data && (
            <>
              <p
                data-testid="drill-courses-pill-progress"
                className="mt-0.5 text-xs text-muted-foreground"
              >
                {courseCount > 0
                  ? `${moduleTotal} модулів у ${courseCount} курсах`
                  : "Курси ще не засіяні — запусти scripts/transpile_drills.py"}
              </p>
              {drillTotal > 0 && (
                <p
                  data-testid="drill-courses-pill-passed"
                  className="mt-0.5 text-xs font-medium text-sky-700"
                >
                  {passedTotal === 0
                    ? `пройдено: 0 / ${drillTotal} — почни з будь-якого`
                    : `пройдено: ${passedTotal} / ${drillTotal}`}
                </p>
              )}
            </>
          )}
        </div>

        <Link
          href="/courses"
          data-testid="drill-courses-pill-cta"
          className="self-center shrink-0 rounded-full border border-sky-500/50 bg-sky-500/10 px-3 py-1.5 text-xs font-medium text-sky-700 hover:bg-sky-500/20 transition-colors"
        >
          Практика
        </Link>
      </div>
    </section>
  );
}
