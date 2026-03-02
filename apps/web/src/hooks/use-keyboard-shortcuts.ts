"use client";

import { useEffect } from "react";
import { useWorkspaceStore, type SectionId } from "@/store/workspace";

const SECTION_SHORTCUTS: Record<string, SectionId> = {
  "1": "notes",
  "2": "practice",
  "3": "analytics",
  "4": "plan",
};

/**
 * Global keyboard shortcuts for the workspace.
 * - Cmd/Ctrl+B: Toggle course tree
 * - Cmd/Ctrl+1~4: Switch sections
 * - Cmd/Ctrl+Enter: Focus chat input
 */
export function useKeyboardShortcuts() {
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      const mod = e.metaKey || e.ctrlKey;
      if (!mod) return;

      // Cmd+B: toggle tree
      if (e.key === "b") {
        e.preventDefault();
        useWorkspaceStore.getState().toggleTree();
        return;
      }

      // Cmd+1~4: switch section
      const section = SECTION_SHORTCUTS[e.key];
      if (section) {
        e.preventDefault();
        useWorkspaceStore.getState().setActiveSection(section);
        return;
      }

      // Cmd+Enter: focus chat input
      if (e.key === "Enter") {
        e.preventDefault();
        const chatInput = document.querySelector<HTMLTextAreaElement>("[data-chat-input]");
        chatInput?.focus();
        return;
      }
    }

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);
}
