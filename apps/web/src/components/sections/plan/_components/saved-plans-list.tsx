"use client";

import type { StudyPlanResponse } from "@/lib/api";
import type { TranslateFn, TranslateFormatFn } from "./plan-helpers";

export function SavedPlansList({
  plans,
  t,
  tf,
}: {
  plans: StudyPlanResponse[];
  t: TranslateFn;
  tf: TranslateFormatFn;
}) {
  if (plans.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">{t("plan.noPlans")}</p>
    );
  }

  return (
    <div className="space-y-2">
      {plans.map((plan) => (
        <div key={plan.id} className="rounded-2xl card-shadow p-3.5">
          <p className="text-sm font-medium text-foreground">{plan.name}</p>
          <p className="text-xs text-muted-foreground mt-1">
            {tf("plan.createdAt", {
              date: new Date(plan.created_at).toLocaleDateString(undefined, {
                month: "short",
                day: "numeric",
                year: "numeric",
              }),
            })}
          </p>
        </div>
      ))}
    </div>
  );
}
