"use client";

import { useCallback, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { useWorkspaceStore } from "@/store/workspace";
import { useRovingTabindex } from "@/hooks/use-roving-tabindex";
import { BLOCK_REGISTRY } from "@/lib/block-system/registry";
import { BlockWrapper } from "./block-wrapper";
import { BlockPalette } from "./block-palette";
import { cn } from "@/lib/utils";

interface BlockGridProps {
  courseId: string;
  aiActionsEnabled: boolean;
}

export function BlockGrid({ courseId, aiActionsEnabled }: BlockGridProps) {
  const blocks = useWorkspaceStore((s) => s.spaceLayout.blocks);
  const columns = useWorkspaceStore((s) => s.spaceLayout.columns);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const gridRef = useRef<HTMLDivElement>(null);
  useRovingTabindex(gridRef, "both");

  const visibleBlocks = blocks.filter((b) => b.visible && !!BLOCK_REGISTRY[b.type]);

  const toggleCollapse = useCallback((blockId: string) => {
    setCollapsed((prev) => ({ ...prev, [blockId]: !prev[blockId] }));
  }, []);

  if (visibleBlocks.length === 0) {
    return null;
  }

  // Map block sizes to grid column spans
  const sizeToSpan = (size: string, cols: number): string => {
    if (cols === 1) return "col-span-1";
    if (size === "full") return cols === 3 ? "col-span-3" : "col-span-2";
    if (size === "large") return cols === 3 ? "col-span-2" : "col-span-2";
    return "col-span-1";
  };

  return (
    <div className="space-y-4">
      <div
        ref={gridRef}
        role="list"
        aria-label="Workspace blocks"
        className="grid gap-5 max-sm:!grid-cols-1"
        style={{
          gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
        }}
      >
        {visibleBlocks
          .sort((a, b) => a.position - b.position)
          .map((block, index) => {
            const isCollapsed = collapsed[block.id] ?? false;
            const regEntry = BLOCK_REGISTRY[block.type];
            const blockLabel = regEntry?.label ?? block.type;

            return (
              <div
                key={block.id}
                role="listitem"
                aria-roledescription="sortable block"
                aria-label={`${blockLabel}, position ${index + 1} of ${visibleBlocks.length}`}
                tabIndex={index === 0 ? 0 : -1}
                className={cn("max-sm:col-span-1", sizeToSpan(block.size, columns))}
                style={{ animation: "block-appear 0.4s ease-out both", animationDelay: `${index * 100}ms` }}
              >
                {/* Mobile collapsible header */}
                <button
                  type="button"
                  className="sm:hidden w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-muted-foreground rounded-t-xl bg-section-header border border-b-0 border-border/60 touch-target"
                  onClick={() => toggleCollapse(block.id)}
                  aria-expanded={!isCollapsed ? "true" : "false"}
                  aria-label={`${isCollapsed ? "Expand" : "Collapse"} ${blockLabel}`}
                >
                  <span>{blockLabel}</span>
                  <ChevronDown className={cn("h-4 w-4 transition-transform", isCollapsed && "-rotate-90")} />
                </button>
                <div className={cn("sm:!block", isCollapsed && "hidden")}>
                  <BlockWrapper
                    block={block}
                    courseId={courseId}
                    aiActionsEnabled={aiActionsEnabled}
                  />
                </div>
              </div>
            );
          })}
      </div>

      <BlockPalette />
    </div>
  );
}
