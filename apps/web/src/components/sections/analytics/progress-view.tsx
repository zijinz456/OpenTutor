"use client";

import { useEffect, useState } from "react";
import { useT } from "@/lib/i18n-context";
import { getCourseProgress, type CourseProgress } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

interface ProgressViewProps {
  courseId: string;
}

const BAR_COLORS = {
  mastered: "bg-zinc-900 dark:bg-zinc-100",
  reviewed: "bg-zinc-600 dark:bg-zinc-400",
  in_progress: "bg-zinc-400 dark:bg-zinc-600",
  not_started: "bg-zinc-300 dark:bg-zinc-600",
} as const;

const GAP_BADGE_COLORS: Record<string, string> = {
  conceptual: "bg-zinc-200 text-zinc-800 dark:bg-zinc-700 dark:text-zinc-200",
  procedural: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  factual: "bg-zinc-200 text-zinc-600 dark:bg-zinc-700 dark:text-zinc-400",
  application: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
};

function fmtTime(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)}m`;
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

export function ProgressView({ courseId }: ProgressViewProps) {
  const t = useT();
  const [data, setData] = useState<CourseProgress | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getCourseProgress(courseId)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  if (error) {
    return (
      <div
        className="flex-1 flex items-center justify-center p-8 text-xs text-muted-foreground"
        data-testid="progress-panel"
      >
        Failed to load progress.
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex-1 flex flex-col gap-3 p-4" data-testid="progress-panel">
        <div className="h-4 w-48 bg-muted animate-pulse rounded" />
        <div className="h-3 w-full bg-muted animate-pulse rounded" />
        <div className="h-3 w-3/4 bg-muted animate-pulse rounded" />
      </div>
    );
  }

  const total = data.total_nodes || 1;
  const segments = [
    { key: "mastered", count: data.mastered, color: BAR_COLORS.mastered },
    { key: "reviewed", count: data.reviewed, color: BAR_COLORS.reviewed },
    { key: "in_progress", count: data.in_progress, color: BAR_COLORS.in_progress },
    { key: "not_started", count: data.not_started, color: BAR_COLORS.not_started },
  ];

  const gapEntries = Object.entries(data.gap_type_breakdown).sort(
    ([, a], [, b]) => b - a,
  );

  return (
    <div
      role="region"
      aria-label="Course progress"
      className="flex-1 flex flex-col gap-4 p-4 overflow-y-auto"
      data-testid="progress-panel"
    >
      <h3 className="text-sm font-medium">Course Completion</h3>

      <div className="grid grid-cols-2 gap-2">
        {[
          { label: t("progress.mastered"), value: `${Math.round(data.average_mastery)}%` },
          { label: t("progress.completion"), value: `${Math.round(data.completion_percent)}%` },
          { label: t("progress.totalTime"), value: fmtTime(data.total_study_minutes) },
          { label: t("progress.notStarted"), value: `${data.not_started}` },
        ].map(({ label, value }) => (
          <div
            key={label}
            className="rounded-2xl card-shadow bg-card p-3.5 flex flex-col gap-0.5"
          >
            <span className="text-xs text-muted-foreground">{label}</span>
            <span className="text-xl font-semibold tabular-nums">{value}</span>
          </div>
        ))}
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>{data.total_nodes} topics</span>
          <span>{Math.round(data.completion_percent)}%</span>
        </div>
        <div role="progressbar" aria-valuenow={Math.round(data.completion_percent)} aria-valuemin={0} aria-valuemax={100} aria-label="Course completion" className="flex h-3 w-full rounded-full overflow-hidden bg-muted">
          {segments.map(({ key, count, color }) => {
            const pct = (count / total) * 100;
            if (pct === 0) return null;
            return (
              <div
                key={key}
                className={`${color} transition-all`}
                style={{ width: `${pct}%` }}
                title={`${key} ${count}`}
              />
            );
          })}
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
          {segments.map(({ key, count, color }) => (
            <span key={key} className="flex items-center gap-1">
              <span className={`inline-block w-2 h-2 rounded-full ${color}`} />
              {key.replace("_", " ")} {count}
            </span>
          ))}
        </div>
      </div>

      {gapEntries.length > 0 ? (
        <div className="space-y-2" data-testid="progress-gap-breakdown">
          <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Gap Breakdown
          </h4>
          <ul className="space-y-1.5">
            {gapEntries.map(([type, count]) => (
              <li key={type} className="flex items-center justify-between text-sm rounded-xl bg-muted/30 p-3.5">
                <Badge
                  variant="outline"
                  className={GAP_BADGE_COLORS[type] ?? "bg-muted text-muted-foreground"}
                >
                  {type}
                </Badge>
                <span className="text-xs tabular-nums text-muted-foreground">{count}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
