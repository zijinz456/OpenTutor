"use client";

import { useEffect, useState } from "react";
import { getReviewSession, type ReviewItem } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

interface ReviewSummaryViewProps {
  courseId: string;
}

const URGENCY_COLORS: Record<string, string> = {
  overdue: "bg-red-500/15 text-red-700 dark:text-red-400",
  urgent: "bg-orange-500/15 text-orange-700 dark:text-orange-400",
  warning: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400",
  ok: "bg-green-500/15 text-green-700 dark:text-green-400",
};

function MasteryBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  return (
    <div className="flex items-center gap-2">
      <div role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Mastery" className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${pct}%`,
            backgroundColor:
              pct >= 80
                ? "var(--color-green-500, #22c55e)"
                : pct >= 50
                  ? "var(--color-yellow-500, #eab308)"
                  : "var(--color-red-500, #ef4444)",
          }}
        />
      </div>
      <span className="text-[10px] text-muted-foreground w-8 text-right">{pct}%</span>
    </div>
  );
}

export function ReviewSummaryView({ courseId }: ReviewSummaryViewProps) {
  const [sessionsByCourse, setSessionsByCourse] = useState<Record<string, ReviewItem[]>>({});
  const [emptyByCourse, setEmptyByCourse] = useState<Record<string, boolean>>({});
  const [failedByCourse, setFailedByCourse] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (sessionsByCourse[courseId] !== undefined || failedByCourse[courseId]) return;
    let cancelled = false;
    getReviewSession(courseId, 10)
      .then((data) => {
        if (cancelled) return;
        setSessionsByCourse((prev) => ({ ...prev, [courseId]: data.items }));
        setEmptyByCourse((prev) => ({ ...prev, [courseId]: data.count === 0 }));
      })
      .catch(() => {
        if (cancelled) return;
        setFailedByCourse((prev) => ({ ...prev, [courseId]: true }));
      });
    return () => {
      cancelled = true;
    };
  }, [courseId, failedByCourse, sessionsByCourse]);

  const items = sessionsByCourse[courseId] ?? [];
  const empty = emptyByCourse[courseId] || failedByCourse[courseId] || false;
  const loading = sessionsByCourse[courseId] === undefined && !failedByCourse[courseId];

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center p-8" data-testid="review-summary-panel">
        <p className="text-xs text-muted-foreground animate-pulse">Loading review session...</p>
      </div>
    );
  }

  if (empty) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center" data-testid="review-summary-panel">
        <h3 className="text-sm font-medium mb-1">Smart Review</h3>
        <p className="text-xs text-muted-foreground max-w-xs">
          No concepts need review right now. Keep learning!
        </p>
      </div>
    );
  }

  const urgentCount = items.filter((i) => i.urgency === "urgent" || i.urgency === "overdue").length;
  const warningCount = items.filter((i) => i.urgency === "warning").length;

  return (
    <div role="region" aria-label="Smart review queue" className="flex-1 flex flex-col overflow-hidden" data-testid="review-summary-panel">
      <div className="px-3 py-2 border-b border-border/60 flex items-center justify-between">
        <span className="text-xs font-medium">LECTOR Smart Review</span>
        <div className="flex gap-1.5">
          {urgentCount > 0 && (
            <Badge variant="outline" className="text-[10px] bg-red-500/10 text-red-600 border-red-200">
              {urgentCount} urgent
            </Badge>
          )}
          {warningCount > 0 && (
            <Badge variant="outline" className="text-[10px] bg-yellow-500/10 text-yellow-600 border-yellow-200">
              {warningCount} warning
            </Badge>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin p-3 space-y-2">
        {items.map((item) => (
          <div
            key={item.concept_id}
            className="rounded-xl bg-muted/30 p-3.5 space-y-1.5"
          >
            <div className="flex items-start justify-between gap-2">
              <span className="text-xs font-medium">{item.concept_label}</span>
              <span
                className={`shrink-0 text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                  URGENCY_COLORS[item.urgency] ?? URGENCY_COLORS.ok
                }`}
              >
                {item.urgency}
              </span>
            </div>
            <MasteryBar value={item.mastery} />
            <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
              <span>Stability: {item.stability_days.toFixed(1)}d</span>
              <span>Recall: {Math.round(item.retrievability * 100)}%</span>
              {item.cluster && <span>Cluster: {item.cluster}</span>}
              {item.last_reviewed && (
                <span>Last: {new Date(item.last_reviewed).toLocaleDateString()}</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
