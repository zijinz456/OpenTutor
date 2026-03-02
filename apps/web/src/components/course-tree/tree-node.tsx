"use client";

import { useState, useCallback, useMemo } from "react";
import {
  ChevronRight,
  Folder,
  FileText,
  File as FileIcon,
} from "lucide-react";
import type { ContentNode } from "@/lib/api";
import { useWorkspaceStore } from "@/store/workspace";
import { cn } from "@/lib/utils";

interface TreeNodeProps {
  node: ContentNode;
  depth: number;
  courseId: string;
}

/**
 * Individual tree node in the course content hierarchy.
 *
 * Backend sends `source_type` ("pdf", "url", "manual") and `level` (0/1/2...).
 * We infer visual type from level + children + source_type.
 */
export function TreeNode({ node, depth, courseId }: TreeNodeProps) {
  const [expanded, setExpanded] = useState(depth < 1);
  const openPdf = useWorkspaceStore((s) => s.openPdf);

  const hasChildren = node.children && node.children.length > 0;

  // Detect PDF: source_type is "pdf" or title ends with .pdf
  const isPdf =
    node.source_type === "pdf" ||
    node.file_type?.toLowerCase().includes("pdf") ||
    (!hasChildren && node.title?.toLowerCase().endsWith(".pdf"));

  const handleClick = useCallback(() => {
    if (hasChildren) {
      setExpanded((prev) => !prev);
      return;
    }

    if (isPdf) {
      // Use file_id if available, otherwise use node.id as fallback
      const fileId = node.file_id || String(node.id);
      openPdf(fileId, node.title);
    }
  }, [hasChildren, isPdf, node.file_id, node.id, node.title, openPdf]);

  // Determine icon based on level, children, and source_type
  const icon = (() => {
    if (isPdf) {
      return <FileIcon className="size-4 shrink-0 text-muted-foreground" />;
    }
    if (hasChildren || node.level === 0 || node.level === 1) {
      return <Folder className="size-4 shrink-0 text-muted-foreground" />;
    }
    return <FileText className="size-4 shrink-0 text-muted-foreground" />;
  })();

  // Inline style for indentation (dynamic values can't be compiled by Tailwind JIT)
  const indentStyle = useMemo(
    () => ({ paddingLeft: `${depth * 16 + 8}px` }),
    [depth],
  );

  return (
    <div data-tree-node data-depth={depth}>
      <button
        type="button"
        onClick={handleClick}
        {...(hasChildren ? { "aria-expanded": expanded } : {})}
        style={indentStyle}
        className={cn(
          "flex w-full items-center gap-1.5 rounded-sm py-1 pr-2 text-sm leading-tight",
          "hover:bg-[var(--tree-hover)] active:bg-[var(--tree-active)]",
          "cursor-pointer select-none transition-colors",
        )}
      >
        {/* Expand/collapse chevron -- invisible spacer for leaf nodes */}
        <span
          className={cn(
            "inline-flex size-4 shrink-0 items-center justify-center transition-transform duration-150",
            expanded && "rotate-90",
            !hasChildren && "invisible",
          )}
          aria-hidden="true"
        >
          <ChevronRight className="size-3.5" />
        </span>

        {icon}

        <span className="truncate">{node.title}</span>
      </button>

      {hasChildren && expanded && (
        <div>
          {node.children!.map((child) => (
            <TreeNode
              key={child.id}
              node={child}
              depth={depth + 1}
              courseId={courseId}
            />
          ))}
        </div>
      )}
    </div>
  );
}
