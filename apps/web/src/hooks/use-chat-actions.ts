"use client";

import { useCallback } from "react";
import { useWorkspaceStore, type SectionId } from "@/store/workspace";
import type { ChatAction } from "@/lib/api";

/**
 * Maps ChatAction types from SSE stream to workspace section switches.
 */
const ACTION_TO_SECTION: Record<string, SectionId> = {
  switch_tab: "notes",
  open_flashcards: "practice",
  load_wrong_answers: "practice",
  generate_study_plan: "plan",
};

export function useChatActions() {
  const setActiveSection = useWorkspaceStore((s) => s.setActiveSection);

  const handleAction = useCallback(
    (action: ChatAction) => {
      // Direct section mapping
      const targetSection = ACTION_TO_SECTION[action.action];
      if (targetSection) {
        setActiveSection(targetSection);
        return;
      }

      // switch_tab with specific value
      if (action.action === "switch_tab" && action.value) {
        const valueMap: Record<string, SectionId> = {
          notes: "notes",
          quiz: "practice",
          flashcards: "practice",
          review: "practice",
          progress: "analytics",
          graph: "analytics",
          profile: "analytics",
          plan: "plan",
          activity: "plan",
        };
        const section = valueMap[action.value];
        if (section) setActiveSection(section);
      }
    },
    [setActiveSection],
  );

  return handleAction;
}
