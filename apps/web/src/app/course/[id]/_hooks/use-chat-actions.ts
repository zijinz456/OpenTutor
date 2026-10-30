"use client";

import { useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useWorkspaceStore } from "@/store/workspace";
import { useChatStore } from "@/store/chat";
import type { ChatAction } from "@/lib/api";
import type { BlockType, BlockSize, LearningMode } from "@/lib/block-system/types";
import { useT, useTF } from "@/lib/i18n-context";

export function useChatActions(courseId: string) {
  const router = useRouter();
  const t = useT();
  const tf = useTF();

  const handleAction = useCallback((action: ChatAction) => {
    const store = useWorkspaceStore.getState();
    const parseSize = (raw?: string): BlockSize | undefined =>
      raw === "small" || raw === "medium" || raw === "large" || raw === "full"
        ? raw
        : undefined;
    const normalizeTemplateId = (raw?: string): string | undefined =>
      raw
        ? raw.trim().toLowerCase().replace(/\s+/g, "_")
        : undefined;

    if (action.action === "data_updated") {
      const section = action.value as string;
      if (section) store.triggerRefresh(section as "notes" | "practice" | "analytics" | "plan");
    } else if (action.action === "focus_topic") {
      const nodeId = action.value as string | undefined;
      if (nodeId) {
        store.setSelectedNodeId(nodeId);
        router.push(`/course/${courseId}/unit/${nodeId}`);
      }
    } else if (action.action === "add_block") {
      const [typeFromValue, inlineSize] = (action.value ?? "").split(":");
      const type = typeFromValue as BlockType | undefined;
      const size = parseSize(action.extra) ?? parseSize(inlineSize);
      if (type) store.addBlock(type, {}, "agent", size);
    } else if (action.action === "remove_block") {
      if (action.value) store.removeBlockByType(action.value as BlockType);
    } else if (action.action === "reorder_blocks") {
      const types = (action.value ?? "").split(",").filter(Boolean) as BlockType[];
      if (types.length) store.reorderBlocks(types);
    } else if (action.action === "resize_block") {
      const [typeFromValue, inlineSize] = (action.value ?? "").split(":");
      const targetType = (typeFromValue || action.value) as BlockType | undefined;
      const nextSize = parseSize(action.extra) ?? parseSize(inlineSize);
      const blocks = store.spaceLayout.blocks;
      const target = targetType ? blocks.find((b) => b.type === targetType) : undefined;
      if (target && nextSize) {
        store.resizeBlock(target.id, nextSize);
      }
    } else if (action.action === "apply_template") {
      const templateId = normalizeTemplateId(action.value);
      if (templateId) store.applyBlockTemplate(templateId);
    } else if (action.action === "agent_insight") {
      store.agentAddBlock(
        "agent_insight",
        { insightType: action.value },
        { reason: action.extra || "", dismissible: true },
      );
    } else if (action.action === "set_learning_mode") {
      const mode = action.value as LearningMode;
      if (mode) store.setLearningMode(mode);
    } else if (action.action === "suggest_mode") {
      const mode = action.value as LearningMode;
      if (mode) {
        store.agentAddBlock(
          "agent_insight",
          { insightType: "mode_suggestion", suggestedMode: mode, reason: action.extra || "" },
          {
            reason: action.extra || tf("course.modeSuggestion.generic", { mode }),
            dismissible: true,
            needsApproval: true,
            approvalCta: t("course.modeSuggestion.switch"),
          },
        );
      }
    }
  }, [courseId, router, t, tf]);

  useEffect(() => {
    const unregister = useChatStore.getState().registerOnAction(handleAction);
    return unregister;
  }, [handleAction]);

  return handleAction;
}
