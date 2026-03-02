"use client";

import { useEffect, useState, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { getCourseProgress, type CourseProgress } from "@/lib/api";
import { useT } from "@/lib/i18n-context";

interface ProgressPanelProps {
  courseId: string;
}

export function ProgressPanel({ courseId }: ProgressPanelProps) {
  const t = useT();
  const [progress, setProgress] = useState<CourseProgress | null>(null);
  const [loading, setLoading] = useState(true);

  const loadProgress = useCallback(async () => {
    setLoading(true);
    try {
      setProgress(await getCourseProgress(courseId));
    } catch {
      // Expected when no progress data exists yet
    } finally {
      setLoading(false);
    }
  }, [courseId]);

  useEffect(() => {
    loadProgress();
  }, [loadProgress]);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <span className="text-sm animate-pulse text-muted-foreground">...</span>
      </div>
    );
  }

  if (!progress || progress.total_nodes === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-4 text-center">
        <div>
          <p className="text-muted-foreground text-sm">
            Upload course materials to start tracking progress
          </p>
        </div>
      </div>
    );
  }

  const segments = [
    {
      label: t("progress.mastered"),
      count: progress.mastered,
      color: "bg-success",
      percent: (progress.mastered / progress.total_nodes) * 100,
    },
    {
      label: t("progress.reviewed"),
      count: progress.reviewed,
      color: "bg-brand",
      percent: (progress.reviewed / progress.total_nodes) * 100,
    },
    {
      label: t("progress.inProgress"),
      count: progress.in_progress,
      color: "bg-warning",
      percent: (progress.in_progress / progress.total_nodes) * 100,
    },
    {
      label: t("progress.notStarted"),
      count: progress.not_started,
      color: "bg-muted",
      percent: (progress.not_started / progress.total_nodes) * 100,
    },
  ];

  const hours = Math.floor(progress.total_study_minutes / 60);
  const mins = progress.total_study_minutes % 60;
  const gapEntries = Object.entries(progress.gap_type_breakdown ?? {}).sort((a, b) => b[1] - a[1]);

  return (
    <div className="flex-1 flex flex-col p-4 gap-4" data-testid="progress-panel">
      {/* Overall completion */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium">Course Completion</span>
          <Badge variant="outline">{progress.completion_percent.toFixed(0)}%</Badge>
        </div>

        {/* Progress bar */}
        <div className="w-full h-3 bg-muted rounded-full overflow-hidden flex">
          {segments.map(
            (seg) =>
              seg.percent > 0 && (
                <div
                  key={seg.label}
                  className={`h-full ${seg.color} transition-all`}
                  style={{ width: `${seg.percent}%` }}
                />
              )
          )}
        </div>

        {/* Legend */}
        <div className="flex flex-wrap gap-3 mt-2">
          {segments.map((seg) => (
            <div key={seg.label} className="flex items-center gap-1 text-xs text-muted-foreground">
              <div className={`w-2 h-2 rounded-full ${seg.color}`} />
              <span>
                {seg.label}: {seg.count}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-3">
        <StatCard
          label={t("progress.totalTime")}
          value={hours > 0 ? `${hours}h ${mins}m` : `${mins}m`}
        />
        <StatCard
          label={t("progress.accuracy")}
          value={`${(progress.average_mastery * 100).toFixed(0)}%`}
        />
        <StatCard
          label="Topics"
          value={`${progress.total_nodes}`}
        />
        <StatCard
          label={t("progress.mastered")}
          value={`${progress.mastered}`}
        />
      </div>

      {gapEntries.length > 0 && (
        <div className="rounded-lg border bg-card p-3" data-testid="progress-gap-breakdown">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium">Learning Gaps</span>
            <Badge variant="outline">{gapEntries.length}</Badge>
          </div>
          <div className="flex flex-wrap gap-2">
            {gapEntries.map(([gapType, count]) => (
              <Badge key={gapType} variant="secondary" className="capitalize">
                {gapType.replaceAll("_", " ")}: {count}
              </Badge>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="p-3 rounded-lg border bg-card">
      <div className="flex items-center gap-2 text-muted-foreground mb-1">
        <span className="text-xs">{label}</span>
      </div>
      <p className="text-lg font-semibold">{value}</p>
    </div>
  );
}
