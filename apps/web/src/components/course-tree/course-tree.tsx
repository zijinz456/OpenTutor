"use client";

import { useMemo, useState } from "react";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useCourseStore } from "@/store/course";
import { useWorkspaceStore } from "@/store/workspace";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { UploadDialog } from "@/components/shared/upload-dialog";
import { TreeNode } from "./tree-node";
import { FileGroup } from "./file-group";
import type { IngestionJobSummary } from "@/lib/api";

interface CourseTreeProps {
  courseId: string;
}

/** Map backend content_category → display label + emoji. */
const CATEGORY_META: Record<string, { label: string; icon: string }> = {
  lecture_slides: { label: "Lecture Slides", icon: "📑" },
  textbook: { label: "Textbook", icon: "📚" },
  assignment: { label: "Assignments", icon: "📝" },
  exam_schedule: { label: "Exam / Schedule", icon: "📅" },
  syllabus: { label: "Syllabus", icon: "📋" },
  notes: { label: "Notes", icon: "🗒️" },
  other: { label: "Other Files", icon: "📄" },
  url: { label: "URLs", icon: "🔗" },
};

/** Category display ordering. */
const CATEGORY_ORDER = [
  "lecture_slides",
  "textbook",
  "syllabus",
  "assignment",
  "exam_schedule",
  "notes",
  "url",
  "other",
];

/** Group completed ingestion jobs by category. */
function groupJobsByCategory(
  jobs: IngestionJobSummary[],
): { category: string; label: string; icon: string; jobs: IngestionJobSummary[] }[] {
  const map = new Map<string, IngestionJobSummary[]>();

  for (const job of jobs) {
    // URL sources get their own category
    let cat = job.source_type === "url" ? "url" : (job.category || "other");
    if (!CATEGORY_META[cat]) cat = "other";
    const arr = map.get(cat);
    if (arr) arr.push(job);
    else map.set(cat, [job]);
  }

  return CATEGORY_ORDER.filter((c) => map.has(c)).map((c) => ({
    category: c,
    label: CATEGORY_META[c]?.label ?? c,
    icon: CATEGORY_META[c]?.icon ?? "📄",
    jobs: map.get(c)!,
  }));
}

/**
 * Course directory tree sidebar.
 *
 * Shows two sections:
 * 1. Source files grouped by auto-classified category
 * 2. Parsed content outline (content tree)
 */
export function CourseTree({ courseId }: CourseTreeProps) {
  const activeCourse = useCourseStore((s) => s.activeCourse);
  const contentTree = useCourseStore((s) => s.contentTree);
  const ingestionJobs = useCourseStore((s) => s.ingestionJobs);
  const [uploadOpen, setUploadOpen] = useState(false);

  const treeCollapsed = useWorkspaceStore((s) => s.treeCollapsed);
  const toggleTree = useWorkspaceStore((s) => s.toggleTree);

  // Only show completed/processing jobs (not failed)
  const visibleJobs = useMemo(
    () => ingestionJobs.filter((j) => j.status !== "failed"),
    [ingestionJobs],
  );

  const fileGroups = useMemo(
    () => groupJobsByCategory(visibleJobs),
    [visibleJobs],
  );

  const hasFiles = fileGroups.length > 0;
  const hasContent = contentTree.length > 0;

  if (treeCollapsed) {
    return (
      <div className="flex h-full flex-col items-center bg-[var(--tree-bg)] py-2">
        <button
          type="button"
          onClick={toggleTree}
          className="rounded-md p-1.5 hover:bg-[var(--tree-hover)] transition-colors cursor-pointer"
          aria-label="Expand sidebar"
        >
          <PanelLeftOpen className="size-4 text-muted-foreground" />
        </button>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full flex-col bg-[var(--tree-bg)]">
      {/* Header */}
      <div className="flex items-center gap-2 border-b px-3 py-2">
        <h2 className="flex-1 truncate text-sm font-semibold">
          {activeCourse?.name ?? "Course Files"}
        </h2>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-7 px-2 text-xs"
          data-testid="workspace-upload-trigger"
          onClick={() => setUploadOpen(true)}
        >
          Upload
        </Button>
      </div>

      {/* Scrollable tree content */}
      <ScrollArea className="flex-1">
        <div className="py-1">
          {!hasFiles && !hasContent && (
            <p className="px-3 py-4 text-xs text-muted-foreground">
              No content yet. Upload files to get started.
            </p>
          )}

          {/* ── Source Files by Category ── */}
          {hasFiles && (
            <div>
              {fileGroups.map((group) => (
                <FileGroup
                  key={group.category}
                  label={group.label}
                  icon={group.icon}
                  jobs={group.jobs}
                />
              ))}
            </div>
          )}

          {/* ── Separator ── */}
          {hasFiles && hasContent && (
            <div className="mx-3 my-1.5 border-t border-border/50" />
          )}

          {/* ── Content Outline ── */}
          {hasContent && (
            <div>
              <div className="px-3 py-1">
                <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Content Outline
                </span>
              </div>
              {contentTree.map((node) => (
                <TreeNode
                  key={node.id}
                  node={node}
                  depth={0}
                  courseId={courseId}
                />
              ))}
            </div>
          )}
        </div>
      </ScrollArea>

      {/* Collapse toggle */}
      <div className="border-t px-2 py-1.5">
        <button
          type="button"
          onClick={toggleTree}
          className="flex w-full items-center gap-2 rounded-sm px-2 py-1 text-xs text-muted-foreground hover:bg-[var(--tree-hover)] transition-colors cursor-pointer"
          aria-label="Collapse sidebar"
        >
          <PanelLeftClose className="size-3.5" />
          <span>Collapse</span>
        </button>
      </div>

      <UploadDialog
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        courseId={courseId}
      />
    </div>
  );
}
