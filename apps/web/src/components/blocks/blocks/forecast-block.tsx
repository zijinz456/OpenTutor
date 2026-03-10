"use client";

import { useEffect, useState } from "react";
import { TrendingUp, BarChart3 } from "lucide-react";
import { getForgettingForecast, getCourseProgress } from "@/lib/api";
import type { BlockComponentProps } from "@/lib/block-system/registry";

interface ForecastData {
  readiness_score?: number;
  concepts_mastered?: number;
  concepts_total?: number;
  risk_concepts?: Array<{ label: string; retrievability: number }>;
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

  const masteryPct = data?.readiness_score ?? progress?.mastery_pct ?? 0;
  const totalConcepts = data?.concepts_total ?? progress?.total_concepts ?? 0;
  const masteredConcepts = data?.concepts_mastered ?? Math.round(totalConcepts * (masteryPct / 100));
  const riskConcepts = data?.risk_concepts ?? [];

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
            Exam Readiness · {masteredConcepts}/{totalConcepts} concepts mastered
          </p>
        </div>
      </div>

      {/* Progress bar */}
      <div
        role="progressbar"
        aria-label={`Exam readiness: ${Math.round(masteryPct)} percent`}
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
      {riskConcepts.length > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-2">At-risk concepts</p>
          <div className="space-y-1.5">
            {riskConcepts.slice(0, 5).map((c, i) => (
              <div key={i} className="flex items-center gap-2 text-xs rounded-xl bg-muted/30 p-3.5">
                <BarChart3 className="size-3 text-destructive shrink-0" aria-hidden="true" />
                <span className="text-foreground flex-1 truncate">{c.label}</span>
                <span className="text-muted-foreground tabular-nums">{Math.round(c.retrievability * 100)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {totalConcepts === 0 && (
        <p className="text-xs text-muted-foreground text-center">
          Complete more practice to build your forecast.
        </p>
      )}
    </div>
  );
}
