"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { Loader2, AlertCircle, AlertTriangle, X, ExternalLink } from "lucide-react";
import { useCourseStore } from "@/store/course";
import type { IngestionJobSummary } from "@/lib/api";

interface IngestionProgressProps {
  courseId: string;
  onIngestionComplete?: () => void;
}

/** Phase label to user-friendly description mapping. */
function describePhase(job: IngestionJobSummary): string {
  if (job.status === "completed") return "Ready";
  if (job.status === "failed") return job.error_message || "Failed";
  return job.phase_label || job.status;
}

/** Check if a failed job is a Canvas 401 / session-expired error. */
function isCanvasSessionError(job: IngestionJobSummary): boolean {
  const msg = job.error_message ?? "";
  return (
    job.status === "failed" &&
    (msg.includes("401") || msg.toLowerCase().includes("session expired") || msg.toLowerCase().includes("re-login"))
  );
}

/** Extract the Canvas domain from an error message like "Canvas API returned 401 for canvas.lms.unimelb.edu.au." */
function extractCanvasDomain(errorMessage: string): string | null {
  const match = errorMessage.match(/401 for ([^\s.]+(?:\.[^\s.]+)+)/);
  return match ? match[1] : null;
}

export function IngestionProgress({ courseId, onIngestionComplete }: IngestionProgressProps) {
  const ingestionJobs = useCourseStore((s) => s.ingestionJobs);
  const fetchIngestionJobs = useCourseStore((s) => s.fetchIngestionJobs);
  const fetchContentTree = useCourseStore((s) => s.fetchContentTree);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const prevActiveCountRef = useRef(0);
  const [canvasAlertDismissed, setCanvasAlertDismissed] = useState(false);

  // Determine active (in-progress) jobs
  const activeJobs = ingestionJobs.filter(
    (j) => !["completed", "failed"].includes(j.status),
  );
  const failedJobs = ingestionJobs.filter(
    (j) => j.status === "failed"
      && j.error_message !== "No content could be extracted",
  );

  // Separate Canvas session errors from other failures
  const canvasSessionErrors = failedJobs.filter(isCanvasSessionError);
  const otherFailedJobs = failedJobs.filter((j) => !isCanvasSessionError(j));

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
      onIngestionComplete?.();
    }
    prevActiveCountRef.current = activeJobs.length;
  }, [activeJobs.length, courseId, fetchContentTree, onIngestionComplete]);

  // Don't render if there are no active or recent failed jobs
  const recentFailedJobs = otherFailedJobs.slice(0, 3);
  const showCanvasAlert = canvasSessionErrors.length > 0 && !canvasAlertDismissed;

  if (activeJobs.length === 0 && recentFailedJobs.length === 0 && !showCanvasAlert) {
    return null;
  }

  // Extract domain from the first Canvas error for the re-login link
  const canvasDomain = canvasSessionErrors.length > 0
    ? extractCanvasDomain(canvasSessionErrors[0].error_message ?? "")
    : null;
  const canvasLoginUrl = canvasDomain ? `https://${canvasDomain}/login` : null;

  return (
    <div className="grid gap-3" role="status" aria-live="polite">
      {/* Canvas session expired -- warning banner */}
      {showCanvasAlert && (
        <div
          role="alert"
          className="rounded-2xl border border-amber-300/60 bg-amber-50/80 px-4 py-3 text-amber-950 card-shadow"
        >
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold">Canvas session expired</p>
              <p className="text-sm text-amber-900/85">
                Your Canvas login session has expired. Please re-login to continue syncing course content.
              </p>
              {canvasLoginUrl && (
                <a
                  href={canvasLoginUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-2 inline-flex items-center gap-1.5 rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm transition-colors hover:bg-amber-700"
                >
                  <ExternalLink className="size-3" />
                  Re-login to Canvas
                </a>
              )}
            </div>
            <button
              type="button"
              onClick={() => setCanvasAlertDismissed(true)}
              className="mt-0.5 shrink-0 text-amber-600 hover:text-amber-900 transition-colors"
              aria-label="Dismiss Canvas session alert"
            >
              <X className="size-4" />
            </button>
          </div>
        </div>
      )}

      {/* Active / failed ingestion jobs */}
      {(activeJobs.length > 0 || recentFailedJobs.length > 0) && (
        <div className="rounded-2xl border border-blue-200/60 bg-blue-50/70 px-3 py-2.5 text-sm card-shadow">
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
                  <div
                    role="progressbar"
                    aria-label={`${job.filename} progress: ${job.progress_percent ?? 0} percent`}
                    className="h-2.5 w-16 overflow-hidden rounded-full bg-blue-200"
                  >
                    <div
                      className="h-full rounded-full bg-brand transition-all duration-500"
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
            <div className="space-y-1" role="alert">
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
      )}
    </div>
  );
}
