"use client";

import Link from "next/link";
import { FileText, FolderOpen, ChevronRight } from "lucide-react";
import type { ContentNode } from "@/lib/api";
import { useT, useTF } from "@/lib/i18n-context";

interface ChapterListProps {
  courseId: string;
  nodes: ContentNode[];
}

/** Categories that are course info/logistics, not learning content */
const INFO_CATEGORIES = new Set(["assignment", "exam_schedule"]);

/**
 * Recursively filter out info-type leaf nodes, keeping structural containers
 * (which may carry a "syllabus" category) as long as they have knowledge
 * children beneath them.
 */
function filterKnowledgeNodes(nodes: ContentNode[]): ContentNode[] {
  return nodes
    .map((n) => ({
      ...n,
      children: n.children ? filterKnowledgeNodes(n.children) : [],
    }))
    .filter((n) => {
      const isInfoLeaf =
        INFO_CATEGORIES.has(n.content_category ?? "") &&
        n.children.length === 0 &&
        n.content === null;
      if (isInfoLeaf) return false;
      // Keep containers that still have children, or leaves with content, or root nodes
      return n.children.length > 0 || n.content !== null || n.level === 0;
    });
}

export function ChapterList({ courseId, nodes }: ChapterListProps) {
  const t = useT();
  const tf = useTF();

  const knowledgeNodes = filterKnowledgeNodes(nodes);

  if (knowledgeNodes.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <FileText className="size-8 mx-auto mb-3 opacity-40" />
        <p className="text-sm">{t("chapter.empty")}</p>
      </div>
    );
  }

  const treeLabel = t("chapter.navLabel") !== "chapter.navLabel" ? t("chapter.navLabel") : "Course chapters";

  return (
    <nav aria-label={treeLabel}>
      <div role="tree" aria-label={treeLabel} className="flex flex-col gap-2">
        {knowledgeNodes.map((node) => {
          const childCount = node.children?.length ?? 0;
          const isFolder = node.level === 0 || node.type === "week" || node.type === "module" || childCount > 0;

          return (
            <div
              key={node.id}
              role="treeitem"
              aria-selected="false"
              {...(isFolder ? { "aria-expanded": true } : {})}
            >
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
            </div>
          );
        })}
      </div>
    </nav>
  );
}
