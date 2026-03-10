"use client";

import type { ReviewItem, StudyGoal } from "@/lib/api";
import { formatDateLabel, getDaysLeft, type TranslateFn } from "./plan-helpers";

export function SelfPacedPath({
  goals,
  reviewItems,
  t,
}: {
  goals: StudyGoal[];
  reviewItems: ReviewItem[];
  t: TranslateFn;
}) {
  const activeGoals = goals.filter((g) => g.status !== "completed");
  const weakConcepts = [...reviewItems]
    .sort((a, b) => a.mastery - b.mastery)
    .slice(0, 8);

  const nextUp = activeGoals.filter((g) => {
    if (!g.target_date) return !!g.next_action;
    const days = getDaysLeft(g.target_date);
    return days != null && days >= 0 && days <= 7;
  });
  const inProgress = activeGoals.filter((g) => !nextUp.some((n) => n.id === g.id));
  const completed = goals.filter((g) => g.status === "completed").slice(0, 6);

  return (
    <div className="space-y-4">
      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
          {t("plan.path.title")}
        </h4>
        {activeGoals.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t("plan.path.empty")}
          </p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="rounded-2xl card-shadow p-3 space-y-2">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t("plan.path.nextUp")}</p>
              {nextUp.length === 0 ? (
                <p className="text-xs text-muted-foreground">{t("plan.path.nextUp.empty")}</p>
              ) : (
                nextUp.map((goal) => (
                  <div key={goal.id} className="rounded-xl bg-muted/30 p-2.5">
                    <p className="text-xs font-medium">{goal.title}</p>
                    <p className="text-[11px] text-muted-foreground mt-0.5">
                      {goal.target_date
                        ? formatDateLabel(goal.target_date, t("plan.deadline.noDate"))
                        : t("plan.deadline.noDate")}
                    </p>
                  </div>
                ))
              )}
            </div>
            <div className="rounded-2xl card-shadow p-3 space-y-2">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t("plan.path.inProgress")}</p>
              {inProgress.length === 0 ? (
                <p className="text-xs text-muted-foreground">{t("plan.path.inProgress.empty")}</p>
              ) : (
                inProgress.slice(0, 6).map((goal) => (
                  <div key={goal.id} className="rounded-xl bg-muted/30 p-2.5">
                    <p className="text-xs font-medium">{goal.title}</p>
                    {goal.next_action ? (
                      <p className="text-[11px] text-brand mt-0.5">{t("plan.path.nextPrefix")} {goal.next_action}</p>
                    ) : (
                      <p className="text-[11px] text-muted-foreground mt-0.5">{t("plan.path.noNextAction")}</p>
                    )}
                  </div>
                ))
              )}
            </div>
            <div className="rounded-2xl card-shadow p-3 space-y-2">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t("plan.path.done")}</p>
              {completed.length === 0 ? (
                <p className="text-xs text-muted-foreground">{t("plan.path.done.empty")}</p>
              ) : (
                completed.map((goal) => (
                  <div key={goal.id} className="rounded-xl bg-muted/30 p-2.5">
                    <p className="text-xs font-medium">{goal.title}</p>
                    <p className="text-[11px] text-muted-foreground mt-0.5">{t("plan.path.completed")}</p>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>

      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
          {t("plan.path.suggestedConcepts")}
        </h4>
        {weakConcepts.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("plan.path.suggestedConcepts.empty")}</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {weakConcepts.map((item) => (
              <div key={item.concept_id} className="rounded-xl bg-muted/30 p-3.5">
                <p className="text-sm font-medium truncate">{item.concept_label}</p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {t("plan.metric.mastery")} {Math.round(item.mastery * 100)}% · {t("plan.metric.stability")} {item.stability_days}d
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
