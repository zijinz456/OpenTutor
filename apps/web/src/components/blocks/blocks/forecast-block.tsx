"use client";

import { useEffect, useState } from "react";
import { TrendingUp, BarChart3 } from "lucide-react";
import { getForgettingForecast, getCourseProgress } from "@/lib/api";
import type { BlockComponentProps } from "@/lib/block-system/registry";

interface ForecastPrediction {
  content_node_id: string | null;
  title: string;
  current_retrievability: number;
  stability_days: number;
  days_until_threshold: number;
  predicted_drop_date: string;
  urgency: "ok" | "warning" | "urgent" | "overdue";
  last_reviewed: string | null;
  mastery_score: number;
}

interface ForecastData {
  course_id: string;
  generated_at: string;
  total_items: number;
  urgent_count: number;
  warning_count: number;
  predictions: ForecastPrediction[];
}

export default function ForecastBlock({ courseId }: BlockComponentProps) {
  const [data, setData] = useState<ForecastData | null>(null);
  const [progress, setProgress] = useState<{ mastery_pct?: number; total_concepts?: number } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setLoading(true);
      Promise.allSettled([
        getForgettingForecast(courseId).then((d) => {
          if (!cancelled) setData(d as ForecastData);
        }),
        getCourseProgress(courseId).then((p) => {
          if (!cancelled) setProgress(p as { mastery_pct?: number; total_concepts?: number });
        }),
      ]).finally(() => {
        if (!cancelled) setLoading(false);
      });
    }, 0);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [courseId]);

  if (loading) {
    return (
      <div role="status" aria-live="polite" className="flex items-center justify-center h-32 text-sm text-muted-foreground animate-pulse">
        Analyzing exam readiness...
      </div>
    );
  }

  const totalItems = data?.total_items ?? 0;
  const urgentCount = data?.urgent_count ?? 0;
  const warningCount = data?.warning_count ?? 0;
  const predictions = data?.predictions ?? [];
  const okCount = totalItems - urgentCount - warningCount;
  const masteryPct = totalItems > 0 ? Math.round((okCount / totalItems) * 100) : (progress?.mastery_pct ?? 0);

  const riskPredictions = predictions.filter(
    (p) => p.urgency === "overdue" || p.urgency === "urgent" || p.urgency === "warning",
  );

  const readinessColor =
    masteryPct >= 80 ? "text-success" :
    masteryPct >= 50 ? "text-warning" :
    "text-destructive";

  return (
    <div role="region" aria-label="Exam readiness forecast" className="p-4 space-y-4">
      {/* Readiness score */}
      <div className="flex items-center gap-4">
        <div className="flex items-center justify-center w-14 h-14 rounded-2xl bg-muted/30">
          <TrendingUp className={`size-6 ${readinessColor}`} aria-hidden="true" />
        </div>
        <div>
          <p className="text-2xl font-bold text-foreground tabular-nums">
            <span className={readinessColor}>{Math.round(masteryPct)}%</span>
          </p>
          <p className="text-xs text-muted-foreground">
            Retention Health · {okCount}/{totalItems} concepts on track
          </p>
        </div>
      </div>

      {/* Summary badges */}
      {totalItems > 0 && (
        <div className="flex gap-2 text-xs">
          {urgentCount > 0 && (
            <span className="rounded-full bg-destructive/10 text-destructive px-2.5 py-0.5 font-medium">
              {urgentCount} urgent
            </span>
          )}
          {warningCount > 0 && (
            <span className="rounded-full bg-warning/10 text-warning px-2.5 py-0.5 font-medium">
              {warningCount} warning
            </span>
          )}
          {okCount > 0 && (
            <span className="rounded-full bg-success/10 text-success px-2.5 py-0.5 font-medium">
              {okCount} on track
            </span>
          )}
        </div>
      )}

      {/* Progress bar */}
      <div
        role="progressbar"
        aria-label={`Retention health: ${Math.round(masteryPct)} percent`}
        className="w-full h-2 bg-muted/40 rounded-full overflow-hidden"
      >
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            masteryPct >= 80 ? "bg-success" : masteryPct >= 50 ? "bg-warning" : "bg-destructive"
          }`}
          style={{ width: `${Math.min(100, masteryPct)}%` }}
          aria-hidden="true"
        />
      </div>

      {/* At-risk concepts */}
      {riskPredictions.length > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-2">At-risk concepts</p>
          <div className="space-y-1.5">
            {riskPredictions.slice(0, 5).map((p, i) => (
              <div key={p.content_node_id ?? i} className="flex items-center gap-2 text-xs rounded-xl bg-muted/30 p-3.5">
                <BarChart3 className={`size-3 shrink-0 ${p.urgency === "ok" ? "text-success" : p.urgency === "warning" ? "text-warning" : "text-destructive"}`} aria-hidden="true" />
                <span className="text-foreground flex-1 truncate">{p.title}</span>
                <span className="text-muted-foreground tabular-nums">{Math.round(p.current_retrievability * 100)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {totalItems === 0 && (
        <p className="text-xs text-muted-foreground text-center">
          Complete more practice to build your forecast.
        </p>
      )}
    </div>
  );
}
