"use client";

import { useState } from "react";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useCourseStore } from "@/store/course";
import { useWorkspaceStore } from "@/store/workspace";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { UploadDialog } from "@/components/shared/upload-dialog";
import { TreeNode } from "./tree-node";

interface CourseTreeProps {
  courseId: string;
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
  const [uploadOpen, setUploadOpen] = useState(false);

  const treeCollapsed = useWorkspaceStore((s) => s.treeCollapsed);
  const toggleTree = useWorkspaceStore((s) => s.toggleTree);

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
          {activeCourse?.name ?? "Course"}
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

      {/* Content TOC */}
      <ScrollArea className="flex-1">
        <div className="py-1">
          {contentTree.length === 0 ? (
            <p className="px-3 py-4 text-xs text-muted-foreground">
              No content yet. Upload files to get started.
            </p>
          ) : (
            contentTree.map((node) => (
              <TreeNode
                key={node.id}
                node={node}
                depth={0}
                courseId={courseId}
              />
            ))
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
