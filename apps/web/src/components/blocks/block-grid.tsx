"use client";

import { useWorkspaceStore } from "@/store/workspace";
import { BlockWrapper } from "./block-wrapper";
import { BlockPalette } from "./block-palette";

interface BlockGridProps {
  courseId: string;
  aiActionsEnabled: boolean;
}

export function BlockGrid({ courseId, aiActionsEnabled }: BlockGridProps) {
  const blocks = useWorkspaceStore((s) => s.spaceLayout.blocks);
  const columns = useWorkspaceStore((s) => s.spaceLayout.columns);

  const visibleBlocks = blocks.filter((b) => b.visible);

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
        className="grid gap-4"
        style={{
          gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
        }}
      >
        {visibleBlocks
          .sort((a, b) => a.position - b.position)
          .map((block) => (
            <div key={block.id} className={sizeToSpan(block.size, columns)}>
              <BlockWrapper
                block={block}
                courseId={courseId}
                aiActionsEnabled={aiActionsEnabled}
              />
            </div>
          ))}
      </div>

      <BlockPalette />
    </div>
  );
}
