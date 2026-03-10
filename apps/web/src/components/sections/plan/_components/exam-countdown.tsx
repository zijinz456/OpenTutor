"use client";

import { useEffect, useState } from "react";
import { listStudyGoals, type StudyGoal } from "@/lib/api";
import { updateUnlockContext } from "@/lib/block-system/feature-unlock";
import type { TranslateFn, TranslateFormatFn } from "./plan-helpers";

interface UpcomingDeadline extends StudyGoal {
  daysLeft: number;
}

export function ExamCountdown({
  courseId,
  t,
  tf,
}: {
  courseId: string;
  t: TranslateFn;
  tf: TranslateFormatFn;
}) {
  const [upcoming, setUpcoming] = useState<UpcomingDeadline[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const goals = await listStudyGoals(courseId, "active");
        if (cancelled) return;
        const now = Date.now();

        if (goals.some((g) => g.target_date)) {
          updateUnlockContext(courseId, { hasDeadline: true });
        }

        const computed = goals
          .filter((g) => g.target_date)
          .map((g) => {
            const target = new Date(g.target_date!).getTime();
            const daysLeft = Math.ceil((target - now) / 86_400_000);
            return { ...g, daysLeft };
          })
          .filter((g) => g.daysLeft >= 0 && g.daysLeft <= 30)
          .sort((a, b) => a.daysLeft - b.daysLeft);
        setUpcoming(computed);
      } catch {
        // ignore
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  if (upcoming.length === 0) return null;

  return (
    <div className="border-b border-border/60 bg-amber-50 dark:bg-amber-950/30 px-3 py-2 space-y-1">
      {upcoming.map((g) => {
        const urgent = g.daysLeft <= 3;
        return (
          <div
            key={g.id}
            className={`flex items-center gap-2 text-xs ${urgent ? "font-semibold text-destructive" : "text-amber-800 dark:text-amber-200"}`}
          >
            <span className="tabular-nums">
              {g.daysLeft === 0
                ? t("plan.banner.today")
                : g.daysLeft === 1
                  ? t("plan.banner.oneDay")
                  : tf("plan.banner.manyDays", { days: g.daysLeft })}
            </span>
            <span className="truncate flex-1">{g.title}</span>
            {urgent ? (
              <span className="shrink-0 rounded bg-destructive/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wider">
                {t("plan.banner.urgent")}
              </span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
