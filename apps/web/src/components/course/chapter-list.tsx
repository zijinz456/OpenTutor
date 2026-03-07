"use client";

import Link from "next/link";
import { FileText, FolderOpen, ChevronRight } from "lucide-react";
import type { ContentNode } from "@/lib/api";
import { useT, useTF } from "@/lib/i18n-context";

interface ChapterListProps {
  courseId: string;
  nodes: ContentNode[];
}

function ChapterCard({ courseId, node }: { courseId: string; node: ContentNode }) {
  const tf = useTF();
  const childCount = node.children?.length ?? 0;
  const isFolder = node.type === "week" || node.type === "module" || childCount > 0;

  return (
    <Link
      href={`/course/${courseId}/unit/${node.id}`}
      className="group flex items-center gap-4 p-4 rounded-xl bg-muted/30 hover:bg-muted/50 transition-colors"
    >
      <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-muted/50 shrink-0">
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
            {tf("chapter.sections", { count: childCount })}
          </p>
        )}
      </div>

      <ChevronRight className="size-4 text-muted-foreground shrink-0 group-hover:text-foreground transition-colors" />
    </Link>
  );
}

export function ChapterList({ courseId, nodes }: ChapterListProps) {
  const t = useT();
  if (nodes.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <FileText className="size-8 mx-auto mb-3 opacity-40" />
        <p className="text-sm">{t("chapter.empty")}</p>
      </div>
    );
  }

  return (
    <nav role="navigation" aria-label="Course chapters">
      <div className="flex flex-col gap-2">
        {nodes.map((node) => (
          <ChapterCard key={node.id} courseId={courseId} node={node} />
        ))}
      </div>
    </nav>
  );
}
