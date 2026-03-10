"use client";

import type { ReviewItem } from "@/lib/api";
import type { TranslateFn } from "./plan-helpers";

export function ExamCoverageChecklist({ reviewItems, t }: { reviewItems: ReviewItem[]; t: TranslateFn }) {
  const weakConcepts = [...reviewItems]
    .sort((a, b) => a.mastery - b.mastery)
    .slice(0, 8);
  if (weakConcepts.length === 0) {
    return (
      <div className="rounded-2xl card-shadow p-3.5">
        <p className="text-xs text-muted-foreground">{t("plan.exam.coverage.empty")}</p>
      </div>
    );
  }
  return (
    <div className="rounded-2xl card-shadow p-3.5 space-y-2.5">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t("plan.exam.coverage")}</p>
      {weakConcepts.map((item) => (
        <div key={`${item.concept_id}-exam`} className="flex items-center gap-2">
          <div className="w-20 h-1.5 bg-muted rounded-full overflow-hidden shrink-0">
            <div className="h-full bg-warning rounded-full" style={{ width: `${Math.round(item.mastery * 100)}%` }} />
          </div>
          <p className="text-xs text-foreground truncate flex-1">{item.concept_label}</p>
          <span className="text-[11px] text-muted-foreground">{Math.round(item.mastery * 100)}%</span>
        </div>
      ))}
    </div>
  );
}
