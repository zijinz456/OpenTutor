"use client";

import { useEffect, useState, useCallback } from "react";
import { Loader2, BookOpen, CheckCircle, Clock, Target } from "lucide-react";
import { Badge } from "@/components/ui/badge";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface CourseProgress {
  course_id: string;
  total_nodes: number;
  mastered: number;
  reviewed: number;
  in_progress: number;
  not_started: number;
  total_study_minutes: number;
  average_mastery: number;
  completion_percent: number;
}

interface ProgressPanelProps {
  courseId: string;
}

export function ProgressPanel({ courseId }: ProgressPanelProps) {
  const [progress, setProgress] = useState<CourseProgress | null>(null);
  const [loading, setLoading] = useState(true);

  const loadProgress = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/progress/courses/${courseId}`);
      if (res.ok) {
        setProgress(await res.json());
      }
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
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!progress || progress.total_nodes === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-4 text-center">
        <div>
          <BookOpen className="h-8 w-8 mx-auto mb-2 text-muted-foreground" />
          <p className="text-muted-foreground text-sm">
            Upload course materials to start tracking progress
          </p>
        </div>
      </div>
    );
  }

  const segments = [
    {
      label: "Mastered",
      count: progress.mastered,
      color: "bg-green-500",
      percent: (progress.mastered / progress.total_nodes) * 100,
    },
    {
      label: "Reviewed",
      count: progress.reviewed,
      color: "bg-blue-500",
      percent: (progress.reviewed / progress.total_nodes) * 100,
    },
    {
      label: "In Progress",
      count: progress.in_progress,
      color: "bg-yellow-500",
      percent: (progress.in_progress / progress.total_nodes) * 100,
    },
    {
      label: "Not Started",
      count: progress.not_started,
      color: "bg-gray-200 dark:bg-gray-700",
      percent: (progress.not_started / progress.total_nodes) * 100,
    },
  ];

  const hours = Math.floor(progress.total_study_minutes / 60);
  const mins = progress.total_study_minutes % 60;

  return (
    <div className="flex-1 flex flex-col p-4 gap-4">
      {/* Overall completion */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium">Course Completion</span>
          <Badge variant="outline">{progress.completion_percent.toFixed(0)}%</Badge>
        </div>

        {/* Progress bar */}
        <div className="w-full h-3 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden flex">
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
          icon={<Clock className="h-4 w-4" />}
          label="Study Time"
          value={hours > 0 ? `${hours}h ${mins}m` : `${mins}m`}
        />
        <StatCard
          icon={<Target className="h-4 w-4" />}
          label="Avg Mastery"
          value={`${(progress.average_mastery * 100).toFixed(0)}%`}
        />
        <StatCard
          icon={<BookOpen className="h-4 w-4" />}
          label="Topics"
          value={`${progress.total_nodes}`}
        />
        <StatCard
          icon={<CheckCircle className="h-4 w-4" />}
          label="Mastered"
          value={`${progress.mastered}`}
        />
      </div>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="p-3 rounded-lg border bg-card">
      <div className="flex items-center gap-2 text-muted-foreground mb-1">
        {icon}
        <span className="text-xs">{label}</span>
      </div>
      <p className="text-lg font-semibold">{value}</p>
    </div>
  );
}
