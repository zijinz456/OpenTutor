"use client";

import Link from "next/link";
import { FileText, FolderOpen, ChevronRight } from "lucide-react";
import type { ContentNode } from "@/lib/api";

interface ChapterListProps {
  courseId: string;
  nodes: ContentNode[];
}

function ChapterCard({ courseId, node }: { courseId: string; node: ContentNode }) {
  const childCount = node.children?.length ?? 0;
  const isFolder = node.type === "week" || node.type === "module" || childCount > 0;

  return (
    <Link
      href={`/course/${courseId}/${node.id}`}
      className="group flex items-center gap-4 p-4 rounded-xl border border-border bg-card hover:bg-accent/50 hover:border-accent transition-colors"
    >
      <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-muted shrink-0">
        {isFolder ? (
          <FolderOpen className="size-5 text-muted-foreground" />
        ) : (
          <FileText className="size-5 text-muted-foreground" />
        )}
      </div>

      <div className="flex-1 min-w-0">
        <h3 className="text-sm font-medium text-foreground truncate group-hover:text-primary transition-colors">
          {node.title}
        </h3>
        {childCount > 0 && (
          <p className="text-xs text-muted-foreground mt-0.5">
            {childCount} {childCount === 1 ? "section" : "sections"}
          </p>
        )}
      </div>

      <ChevronRight className="size-4 text-muted-foreground shrink-0 group-hover:text-foreground transition-colors" />
    </Link>
  );
}

export function ChapterList({ courseId, nodes }: ChapterListProps) {
  if (nodes.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <FileText className="size-8 mx-auto mb-3 opacity-40" />
        <p className="text-sm">No content yet. Upload materials to get started.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {nodes.map((node) => (
        <ChapterCard key={node.id} courseId={courseId} node={node} />
      ))}
    </div>
  );
}
