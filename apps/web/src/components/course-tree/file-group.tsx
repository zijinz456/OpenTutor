"use client";

import { useState, useMemo, useCallback } from "react";
import { ChevronRight, Loader2, ExternalLink } from "lucide-react";
import type { IngestionJobSummary } from "@/lib/api";
import { getFileUrl } from "@/lib/api";
import { useWorkspaceStore } from "@/store/workspace";
import { cn } from "@/lib/utils";

interface FileGroupProps {
  category: string;
  label: string;
  icon: string;
  jobs: IngestionJobSummary[];
  courseId: string;
}

/**
 * Expandable category group in the course tree sidebar.
 * Shows a folder-like header with child file items.
 */
export function FileGroup({ category, label, icon, jobs, courseId }: FileGroupProps) {
  const [expanded, setExpanded] = useState(true);
  const openPdf = useWorkspaceStore((s) => s.openPdf);

  return (
    <div role="treeitem" aria-expanded={expanded}>
      {/* Category header */}
      <button
        type="button"
        onClick={() => setExpanded((p) => !p)}
        className={cn(
          "flex w-full items-center gap-1.5 py-1 pr-2 text-sm leading-tight",
          "hover:bg-[var(--tree-hover)] active:bg-[var(--tree-active)]",
          "cursor-pointer select-none transition-colors",
        )}
        style={{ paddingLeft: "8px" }}
      >
        <span
          className={cn(
            "inline-flex size-4 shrink-0 items-center justify-center transition-transform duration-150",
            expanded && "rotate-90",
          )}
          aria-hidden="true"
        >
          <ChevronRight className="size-3.5" />
        </span>
        <span className="text-sm">{icon}</span>
        <span className="truncate font-medium text-sm">{label}</span>
        <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">
          {jobs.length}
        </span>
      </button>

      {/* File items */}
      {expanded && (
        <div role="group">
          {jobs.map((job) => (
            <FileItem
              key={job.id}
              job={job}
              courseId={courseId}
              onOpenPdf={openPdf}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Single file item ── */

interface FileItemProps {
  job: IngestionJobSummary;
  courseId: string;
  onOpenPdf: (fileId: string, fileName: string) => void;
}

function FileItem({ job, courseId, onOpenPdf }: FileItemProps) {
  const isPdf =
    job.source_type === "file" &&
    (job.filename?.toLowerCase().endsWith(".pdf") ?? false);
  const isUrl = job.source_type === "url";
  const isProcessing = job.status !== "completed";

  const displayName = useMemo(() => {
    if (isUrl) {
      // Show a cleaned-up URL
      try {
        const u = new URL(job.filename);
        return u.hostname + (u.pathname !== "/" ? u.pathname : "");
      } catch {
        return job.filename;
      }
    }
    return job.filename;
  }, [job.filename, isUrl]);

  const handleClick = useCallback(() => {
    if (isProcessing) return;
    if (isPdf) {
      onOpenPdf(job.id, job.filename);
    }
  }, [isProcessing, isPdf, job.id, job.filename, onOpenPdf]);

  return (
    <button
      type="button"
      role="treeitem"
      onClick={handleClick}
      disabled={isProcessing}
      className={cn(
        "flex w-full items-center gap-1.5 py-1 pr-2 text-xs leading-tight",
        "hover:bg-[var(--tree-hover)] active:bg-[var(--tree-active)]",
        "cursor-pointer select-none transition-colors",
        "disabled:opacity-50 disabled:cursor-default",
      )}
      style={{ paddingLeft: "40px" }}
      title={job.filename}
    >
      {isProcessing ? (
        <Loader2 className="size-3 shrink-0 animate-spin text-muted-foreground" />
      ) : isUrl ? (
        <ExternalLink className="size-3 shrink-0 text-muted-foreground" />
      ) : (
        <span className="size-3 shrink-0" />
      )}
      <span className="truncate">{displayName}</span>
      {isProcessing && (
        <span className="ml-auto text-[10px] text-muted-foreground whitespace-nowrap">
          {job.phase_label || job.status}
        </span>
      )}
    </button>
  );
}
