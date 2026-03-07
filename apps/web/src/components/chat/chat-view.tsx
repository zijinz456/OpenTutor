"use client";

import { useEffect } from "react";
import { useChatStore } from "@/store/chat";
import { useWorkspaceStore, type SectionId } from "@/store/workspace";
import { ChatHeader } from "@/components/chat/chat-header";
import { MessageList } from "@/components/chat/message-list";
import { ChatInput } from "@/components/chat/chat-input";
import { ToolStatus } from "@/components/chat/tool-status";
import { AiFeatureBlocked } from "@/components/shared/ai-feature-blocked";
import type { ChatAction } from "@/lib/api";

interface ChatViewProps {
  courseId: string;
  aiActionsEnabled?: boolean;
}

/**
 * Main chat container.
 *
 * Sits at the bottom of the workspace (full width, like a VS Code terminal
 * panel). Layout: header + message list + tool-status bar + input bar.
 */
export function ChatView({ courseId, aiActionsEnabled = true }: ChatViewProps) {
  const messages = useChatStore((s) => s.messages);
  const toolStatus = useChatStore((s) => s.toolStatus);
  const setCourseContext = useChatStore((s) => s.setCourseContext);
  const loadSessions = useChatStore((s) => s.loadSessions);
  const setOnAction = useChatStore((s) => s.setOnAction);
  const setActiveSection = useWorkspaceStore((s) => s.setActiveSection);
  const triggerRefresh = useWorkspaceStore((s) => s.triggerRefresh);

  // Set course context and load sessions on mount / courseId change.
  useEffect(() => {
    setCourseContext(courseId);
    void loadSessions(courseId, { restoreLatest: true });
  }, [courseId, setCourseContext, loadSessions]);

  // Register the onAction handler to bridge chat actions to workspace sections.
  useEffect(() => {
    const handleAction = (action: ChatAction) => {
      const type = action.action;

      if (type === "switch_tab" || type === "open_section") {
        const target = action.value as SectionId | undefined;
        if (target) {
          setActiveSection(target);
        }
        return;
      }

      if (type === "open_quiz" || type === "add_to_quiz") {
        setActiveSection("practice");
        return;
      }

      if (type === "open_plan" || type === "show_plan") {
        setActiveSection("plan");
        return;
      }

      if (type === "open_notes" || type === "add_to_notes") {
        setActiveSection("notes");
        return;
      }

      // Agent tool completed — refresh the target section and switch to it.
      if (type === "data_updated") {
        const section = action.value as SectionId | undefined;
        if (section) {
          triggerRefresh(section);
          setActiveSection(section);
        }
        return;
      }
    };

    setOnAction(handleAction);
    return () => setOnAction(() => {});
  }, [setOnAction, setActiveSection, triggerRefresh]);

  return (
    <div className="flex h-full flex-col bg-background">
      <ChatHeader courseId={courseId} />

      <MessageList messages={messages} />

      <ToolStatus status={toolStatus} />

      {!aiActionsEnabled ? <AiFeatureBlocked compact className="mx-3 mb-2" /> : null}

      <ChatInput courseId={courseId} disabled={!aiActionsEnabled} />
    </div>
  );
}
