"use client";

import { Suspense, useMemo } from "react";
import Link from "next/link";
import { X, Check, Sparkles, Maximize2, AlertTriangle, Lock } from "lucide-react";
import { ErrorBoundary } from "@/components/shared/error-boundary";
import { BLOCK_REGISTRY } from "@/lib/block-system/registry";
import type { BlockInstance, BlockType, LearningMode } from "@/lib/block-system/types";
import { updateUnlockContext, isBlockUnlocked, getUnlockContext } from "@/lib/block-system/feature-unlock";
import { logAgentDecision } from "@/lib/api";
import { useWorkspaceStore } from "@/store/workspace";
import { useCourseStore } from "@/store/course";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n-context";
import { toast } from "sonner";
import { recordBlockEvent, useBlockEngagement } from "@/hooks/use-block-engagement";

/** Block types that open a right-side drawer instead of navigating. */
const BLOCK_DRAWER_TYPES = new Set<BlockType>(["notes"]);

const BLOCK_FULL_PAGE_LINKS: Partial<Record<BlockType, (courseId: string) => string>> = {
  quiz: (courseId) => `/course/${courseId}/practice?tab=quiz`,
  flashcards: (courseId) => `/course/${courseId}/practice?tab=flashcards`,
  knowledge_graph: (courseId) => `/course/${courseId}/graph`,
  plan: (courseId) => `/course/${courseId}/plan`,
  review: (courseId) => `/course/${courseId}/review`,
  progress: (courseId) => `/course/${courseId}/profile?tab=progress`,
  wrong_answers: (courseId) => `/course/${courseId}/wrong-answers`,
  forecast: (courseId) => `/course/${courseId}/profile?tab=forecast`,
};

interface BlockWrapperProps {
  block: BlockInstance;
  courseId: string;
  aiActionsEnabled: boolean;
}

export function BlockWrapper({ block, courseId, aiActionsEnabled }: BlockWrapperProps) {
  const t = useT();
  const removeBlock = useWorkspaceStore((s) => s.removeBlock);
  const addBlock = useWorkspaceStore((s) => s.addBlock);
  const approveAgentBlock = useWorkspaceStore((s) => s.approveAgentBlock);
  const dismissAgentBlock = useWorkspaceStore((s) => s.dismissAgentBlock);
  const setLearningMode = useWorkspaceStore((s) => s.setLearningMode);
  const applyBlockTemplate = useWorkspaceStore((s) => s.applyBlockTemplate);
  const currentMode = useWorkspaceStore((s) => s.spaceLayout.mode);
  const courses = useCourseStore((s) => s.courses);

  const setNotesDrawerOpen = useWorkspaceStore((s) => s.setNotesDrawerOpen);

  const engagementRef = useBlockEngagement(block.id, block.type, courseId);

  // Feature unlock check
  const { unlocked, unlockHint, reason: unlockReason } = useMemo(() => {
    const ctx = { ...getUnlockContext(courseId, courses.length), mode: currentMode ?? undefined };
    return isBlockUnlocked(block.type, ctx);
  }, [block.type, courseId, courses.length, currentMode]);

  const entry = BLOCK_REGISTRY[block.type];
  if (!entry) return null;

  const Component = entry.component;
  const isAgent = block.source === "agent";
  const needsApproval = isAgent && block.agentMeta?.needsApproval;
  const insightType = block.type === "agent_insight" ? (block.config.insightType as string | undefined) : undefined;
  const suggestionSignals = Array.isArray(block.config.suggestionSignals)
    ? block.config.suggestionSignals.filter((signal): signal is string => typeof signal === "string")
    : [];

  const logModeSuggestionDecision = (action: string, suggestedMode?: LearningMode) => {
    void logAgentDecision({
      course_id: courseId,
      action,
      title: entry.label,
      reason: typeof block.config.reason === "string" ? block.config.reason : block.agentMeta?.reason,
      decision_type: "mode_suggestion",
      source: "course_workspace",
      top_signal_type: "manual_override",
      metadata_json: {
        suggested_mode: suggestedMode,
        approval_cta: block.agentMeta?.approvalCta,
        signals: suggestionSignals,
      },
    }).catch(() => undefined);
  };

  const handleApprove = () => {
    // Apply the intended operation directly for high-impact Tier-2 suggestions.
    if (insightType === "mode_suggestion") {
      const suggestedMode = block.config.suggestedMode as LearningMode | undefined;
      if (suggestedMode) {
        logModeSuggestionDecision("approve_mode_suggestion", suggestedMode);
        setLearningMode(suggestedMode);
        updateUnlockContext(courseId, { mode: suggestedMode });
        dismissAgentBlock(block.id);
        return;
      }
    }
    if (insightType === "layout_suggestion") {
      const suggestedTemplate = block.config.suggestedTemplate as string | undefined;
      if (suggestedTemplate) {
        applyBlockTemplate(suggestedTemplate);
        dismissAgentBlock(block.id);
        return;
      }
    }
    if (insightType === "feature_unlock") {
      const suggestedBlockType = block.config.suggestedBlockType as BlockType | undefined;
      if (suggestedBlockType) {
        const exists = useWorkspaceStore.getState().spaceLayout.blocks.some(
          (b) => b.type === suggestedBlockType,
        );
        if (!exists) {
          addBlock(suggestedBlockType, {}, "agent");
        }
        dismissAgentBlock(block.id);
        return;
      }
    }
    approveAgentBlock(block.id);
    recordBlockEvent(courseId, block.type, "approve");
  };

  const handleDismiss = () => {
    if (insightType === "mode_suggestion") {
      const suggestedMode = block.config.suggestedMode as LearningMode | undefined;
      logModeSuggestionDecision("dismiss_mode_suggestion", suggestedMode);
    }
    dismissAgentBlock(block.id);
    recordBlockEvent(courseId, block.type, "dismiss");
  };

  return (
    <div
      ref={engagementRef}
      role="region"
      aria-label={entry.label}
      tabIndex={0}
      className={cn(
        "rounded-2xl bg-card overflow-hidden flex flex-col card-shadow",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        isAgent && "ring-1 ring-brand/20 bg-brand-muted/20",
        needsApproval && "ring-1 ring-warning/30 bg-warning-muted/20",
      )}
    >
      {/* Header bar */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-border/40">
        <span className="text-sm font-medium text-foreground flex-1 truncate">
          {entry.label}
        </span>

        {BLOCK_DRAWER_TYPES.has(block.type) && (
          <button
            type="button"
            onClick={() => {
              if (block.type === "notes") setNotesDrawerOpen(true);
            }}
            className="text-muted-foreground hover:text-foreground transition-colors p-1"
            aria-label={t("block.openFullPage")}
            title={t("block.openFullPage")}
          >
            <Maximize2 className="size-3.5" />
          </button>
        )}

        {BLOCK_FULL_PAGE_LINKS[block.type] && (
          <Link
            href={BLOCK_FULL_PAGE_LINKS[block.type]!(courseId)}
            className="text-muted-foreground hover:text-foreground transition-colors p-1"
            aria-label={t("block.openFullPage")}
            title={t("block.openFullPage")}
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
              onClick={handleApprove}
              className="inline-flex items-center gap-1 text-[11px] font-medium text-success bg-success-muted px-2.5 py-1 rounded-md hover:bg-success/20 transition-colors"
              aria-label={block.agentMeta?.approvalCta || t("block.approve")}
            >
              <Check className="size-3" />
              {block.agentMeta?.approvalCta || t("block.approve")}
            </button>
            <button
              onClick={handleDismiss}
              className="inline-flex items-center gap-1 text-[11px] font-medium text-muted-foreground hover:text-destructive px-1.5 py-1 rounded-md transition-colors"
              aria-label={t("block.dismiss")}
            >
              <X className="size-3" />
            </button>
          </>
        )}

        {!needsApproval && isAgent && block.agentMeta?.dismissible && (
          <button
            onClick={handleDismiss}
            className="text-muted-foreground hover:text-foreground transition-colors p-1 -mr-1"
            aria-label={t("block.dismiss")}
          >
            <X className="size-3.5" />
          </button>
        )}

        {block.source === "user" && (
          <button
            onClick={() => {
              removeBlock(block.id);
              recordBlockEvent(courseId, block.type, "manual_remove");
              toast(t("block.removed"), {
                action: {
                  label: t("block.undo"),
                  onClick: () => useWorkspaceStore.getState().undoRemoveBlock(),
                },
                duration: 5000,
              });
            }}
            className="text-muted-foreground hover:text-destructive transition-colors p-1 -mr-1"
            aria-label={t("block.remove")}
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
      <div className="flex-1 min-h-0 overflow-auto relative">
        <ErrorBoundary
          fallback={
            <div className="flex flex-col items-center justify-center h-32 gap-2 text-center p-4">
              <AlertTriangle className="size-5 text-destructive/60" />
              <p className="text-xs text-muted-foreground">
                This block encountered an error.
              </p>
            </div>
          }
        >
          <Suspense
            fallback={
              <div className="flex items-center justify-center h-32 text-sm text-muted-foreground">
                {t("block.loading")}
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
        </ErrorBoundary>

        {/* Locked overlay */}
        {!unlocked && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-background/80 backdrop-blur-sm rounded-b-2xl z-20 group">
            <div className="flex flex-col items-center gap-2 p-4 text-center">
              <div className="flex size-10 items-center justify-center rounded-full bg-muted ring-2 ring-border group-hover:ring-brand/30 transition-all">
                <Lock className="size-5 text-muted-foreground group-hover:text-brand transition-colors" />
              </div>
              <p className="text-sm font-medium text-foreground">{entry.label} 已锁定</p>
              {unlockHint && (
                <p className="text-xs text-muted-foreground max-w-[200px]">{unlockHint}</p>
              )}
              {unlockReason && (
                <p className="text-[11px] text-muted-foreground/70 max-w-[220px]">{unlockReason}</p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
