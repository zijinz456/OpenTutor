"use client";

import { Suspense } from "react";
import Link from "next/link";
import { X, Check, Sparkles, Maximize2 } from "lucide-react";
import { BLOCK_REGISTRY } from "@/lib/block-system/registry";
import type { BlockInstance, BlockType } from "@/lib/block-system/types";
import { useWorkspaceStore } from "@/store/workspace";
import { cn } from "@/lib/utils";

const BLOCK_FULL_PAGE_ROUTES: Partial<Record<BlockType, string>> = {
  notes: "notes",
  quiz: "practice",
  flashcards: "practice",
  knowledge_graph: "graph",
  plan: "plan",
  review: "review",
  progress: "profile",
};

interface BlockWrapperProps {
  block: BlockInstance;
  courseId: string;
  aiActionsEnabled: boolean;
}

export function BlockWrapper({ block, courseId, aiActionsEnabled }: BlockWrapperProps) {
  const removeBlock = useWorkspaceStore((s) => s.removeBlock);
  const approveAgentBlock = useWorkspaceStore((s) => s.approveAgentBlock);
  const dismissAgentBlock = useWorkspaceStore((s) => s.dismissAgentBlock);

  const entry = BLOCK_REGISTRY[block.type];
  if (!entry) return null;

  const Component = entry.component;
  const isAgent = block.source === "agent";
  const needsApproval = isAgent && block.agentMeta?.needsApproval;

  return (
    <div
      className={cn(
        "rounded-xl border bg-card overflow-hidden flex flex-col",
        isAgent && "border-brand/30 bg-brand-muted/30",
        needsApproval && "border-warning/40 bg-warning-muted/40",
      )}
    >
      {/* Header bar */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border/60 bg-section-header/50">
        <span className="text-sm font-medium text-foreground flex-1 truncate">
          {entry.label}
        </span>

        {BLOCK_FULL_PAGE_ROUTES[block.type] && (
          <Link
            href={`/course/${courseId}/${BLOCK_FULL_PAGE_ROUTES[block.type]}`}
            className="text-muted-foreground hover:text-foreground transition-colors p-1"
            aria-label="Open full page"
            title="Open full page"
          >
            <Maximize2 className="size-3.5" />
          </Link>
        )}

        {isAgent && block.agentMeta && (
          <span className="inline-flex items-center gap-1 text-[11px] font-medium text-brand bg-brand-muted px-2 py-0.5 rounded-full">
            <Sparkles className="size-3" />
            AI
          </span>
        )}

        {needsApproval && (
          <>
            <button
              onClick={() => approveAgentBlock(block.id)}
              className="inline-flex items-center gap-1 text-[11px] font-medium text-success bg-success-muted px-2.5 py-1 rounded-md hover:bg-success/20 transition-colors"
            >
              <Check className="size-3" />
              {block.agentMeta?.approvalCta || "Approve"}
            </button>
            <button
              onClick={() => dismissAgentBlock(block.id)}
              className="inline-flex items-center gap-1 text-[11px] font-medium text-muted-foreground hover:text-destructive px-1.5 py-1 rounded-md transition-colors"
            >
              <X className="size-3" />
            </button>
          </>
        )}

        {!needsApproval && isAgent && block.agentMeta?.dismissible && (
          <button
            onClick={() => dismissAgentBlock(block.id)}
            className="text-muted-foreground hover:text-foreground transition-colors p-1 -mr-1"
            aria-label="Dismiss"
          >
            <X className="size-3.5" />
          </button>
        )}

        {block.source === "user" && (
          <button
            onClick={() => removeBlock(block.id)}
            className="text-muted-foreground hover:text-destructive transition-colors p-1 -mr-1"
            aria-label="Remove block"
          >
            <X className="size-3.5" />
          </button>
        )}
      </div>

      {/* Agent reason banner */}
      {isAgent && block.agentMeta?.reason && (
        <div className="px-4 py-2 text-xs text-brand bg-brand-muted/50 border-b border-brand/10">
          {block.agentMeta.reason}
        </div>
      )}

      {/* Block content */}
      <div className="flex-1 min-h-0 overflow-auto">
        <Suspense
          fallback={
            <div className="flex items-center justify-center h-32 text-sm text-muted-foreground">
              Loading...
            </div>
          }
        >
          <Component
            courseId={courseId}
            blockId={block.id}
            config={block.config}
            aiActionsEnabled={aiActionsEnabled}
          />
        </Suspense>
      </div>
    </div>
  );
}
