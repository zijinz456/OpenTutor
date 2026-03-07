"use client";

import { useEffect, useRef, useCallback } from "react";
import { Loader2, AlertCircle } from "lucide-react";
import { useCourseStore } from "@/store/course";
import type { IngestionJobSummary } from "@/lib/api";

interface IngestionProgressProps {
  courseId: string;
}

/** Phase label to user-friendly description mapping. */
function describePhase(job: IngestionJobSummary): string {
  if (job.status === "completed") return "Ready";
  if (job.status === "failed") return job.error_message || "Failed";
  return job.phase_label || job.status;
}

export function IngestionProgress({ courseId }: IngestionProgressProps) {
  const ingestionJobs = useCourseStore((s) => s.ingestionJobs);
  const fetchIngestionJobs = useCourseStore((s) => s.fetchIngestionJobs);
  const fetchContentTree = useCourseStore((s) => s.fetchContentTree);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const prevActiveCountRef = useRef(0);

  // Determine active (in-progress) jobs
  const activeJobs = ingestionJobs.filter(
    (j) => !["completed", "failed"].includes(j.status),
  );
  const failedJobs = ingestionJobs.filter((j) => j.status === "failed");

  // Compute aggregate progress for active jobs
  const avgProgress =
    activeJobs.length > 0
      ? Math.round(
          activeJobs.reduce((sum, j) => sum + (j.progress_percent || 0), 0) /
            activeJobs.length,
        )
      : 0;

  const refreshJobs = useCallback(() => {
    void fetchIngestionJobs(courseId);
  }, [courseId, fetchIngestionJobs]);

  // Poll while there are active jobs
  useEffect(() => {
    if (activeJobs.length > 0) {
      if (!intervalRef.current) {
        intervalRef.current = setInterval(refreshJobs, 3000);
      }
    } else {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    }
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [activeJobs.length, refreshJobs]);

  // When active jobs finish (count goes from >0 to 0), refresh content tree
  useEffect(() => {
    if (prevActiveCountRef.current > 0 && activeJobs.length === 0) {
      void fetchContentTree(courseId);
    }
    prevActiveCountRef.current = activeJobs.length;
  }, [activeJobs.length, courseId, fetchContentTree]);

  // Don't render if there are no active or recent failed jobs
  const recentFailedJobs = failedJobs.slice(0, 3);

  if (activeJobs.length === 0 && recentFailedJobs.length === 0) {
    return null;
  }

  return (
    <div className="rounded-lg border border-blue-200/60 bg-blue-50/70 px-3 py-2 text-sm">
      {activeJobs.length > 0 && (
        <div className="flex items-center gap-2">
          <Loader2 className="size-3.5 shrink-0 animate-spin text-blue-600" />
          <span className="text-blue-900">
            Processing {activeJobs.length} file{activeJobs.length !== 1 ? "s" : ""}...
            {avgProgress > 0 && ` (${avgProgress}%)`}
          </span>
        </div>
      )}

      {activeJobs.length > 0 && activeJobs.length <= 3 && (
        <div className="mt-1.5 space-y-1 pl-5">
          {activeJobs.map((job) => (
            <div key={job.id} className="flex items-center gap-2 text-xs text-blue-800/80">
              <div className="h-1 w-16 overflow-hidden rounded-full bg-blue-200">
                <div
                  className="h-full rounded-full bg-blue-500 transition-all duration-500"
                  style={{ width: `${job.progress_percent || 0}%` }}
                />
              </div>
              <span className="truncate">
                {job.filename}: {describePhase(job)}
              </span>
            </div>
          ))}
        </div>
      )}

      {activeJobs.length === 0 && recentFailedJobs.length > 0 && (
        <div className="space-y-1">
          {recentFailedJobs.map((job) => (
            <div key={job.id} className="flex items-center gap-2 text-red-800">
              <AlertCircle className="size-3.5 shrink-0" />
              <span className="truncate">
                {job.filename}: {job.error_message || "Processing failed"}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
