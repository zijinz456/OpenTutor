"use client";

import type { ReviewItem } from "@/lib/api";
import type { TranslateFn } from "./plan-helpers";

export function MaintenanceQueue({ reviewItems, t }: { reviewItems: ReviewItem[]; t: TranslateFn }) {
  const rank = { overdue: 0, urgent: 1, warning: 2 } as const;
  const dueItems = reviewItems
    .filter((i) => i.urgency === "overdue" || i.urgency === "urgent" || i.urgency === "warning")
    .sort((a, b) => {
      const ra = rank[a.urgency as keyof typeof rank] ?? 99;
      const rb = rank[b.urgency as keyof typeof rank] ?? 99;
      if (ra !== rb) return ra - rb;
      return a.retrievability - b.retrievability;
    });

  if (dueItems.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("plan.maintenance.empty")}</p>;
  }

  return (
    <div className="space-y-2.5">
      {dueItems.map((item) => {
        const urgencyStyle =
          item.urgency === "overdue"
            ? "text-destructive"
            : item.urgency === "urgent"
              ? "text-warning"
              : "text-muted-foreground";

        return (
          <div key={`${item.concept_id}-${item.urgency}`} className="rounded-2xl card-shadow p-3.5">
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-foreground truncate">{item.concept_label}</p>
                <p className="text-xs text-muted-foreground mt-1">
                  {t("plan.metric.retrievability")} {Math.round(item.retrievability * 100)}% · {t("plan.metric.stability")} {item.stability_days}d
                </p>
              </div>
              <span className={`text-xs font-medium uppercase ${urgencyStyle}`}>{item.urgency}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
