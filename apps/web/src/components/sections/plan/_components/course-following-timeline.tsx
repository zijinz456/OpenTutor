"use client";

import type { StudyGoal } from "@/lib/api";
import { formatDateLabel, getDaysLeft, type TranslateFn, type TranslateFormatFn } from "./plan-helpers";

export function CourseFollowingTimeline({
  goals,
  t,
  tf,
}: {
  goals: StudyGoal[];
  t: TranslateFn;
  tf: TranslateFormatFn;
}) {
  const timeline = goals
    .filter((g) => g.target_date)
    .sort((a, b) => new Date(a.target_date!).getTime() - new Date(b.target_date!).getTime());

  if (timeline.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {t("plan.timeline.empty")}
      </p>
    );
  }

  return (
    <div className="space-y-2.5">
      {timeline.map((goal) => {
        const daysLeft = getDaysLeft(goal.target_date);
        const urgencyClass =
          daysLeft == null
            ? "text-muted-foreground"
            : daysLeft < 0
              ? "text-destructive"
              : daysLeft <= 3
                ? "text-warning"
                : "text-muted-foreground";
        return (
          <div key={goal.id} className="rounded-2xl card-shadow p-3.5">
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-foreground">{goal.title}</p>
                {goal.next_action ? (
                  <p className="text-xs text-muted-foreground mt-1">{t("plan.path.nextPrefix")} {goal.next_action}</p>
                ) : null}
              </div>
              <div className="text-right shrink-0">
                <p className="text-xs text-foreground">{formatDateLabel(goal.target_date, t("plan.deadline.noDate"))}</p>
                <p className={`text-[11px] mt-0.5 ${urgencyClass}`}>
                  {daysLeft == null
                    ? t("plan.deadline.none")
                    : daysLeft < 0
                      ? t("plan.deadline.overdue")
                      : daysLeft === 0
                        ? t("plan.deadline.today")
                        : tf("plan.deadline.daysLeft", { days: daysLeft })}
                </p>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
