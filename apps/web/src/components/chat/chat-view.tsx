"use client";

import { useEffect } from "react";
import { useChatStore } from "@/store/chat";
import { useWorkspaceStore, type SectionId } from "@/store/workspace";
import { ChatHeader } from "@/components/chat/chat-header";
import { MessageList } from "@/components/chat/message-list";
import { GeneratedQuizCard } from "@/components/chat/generated-quiz-card";
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
export function ChatView({
  courseId,
  aiActionsEnabled = true,
}: ChatViewProps) {
  const messages = useChatStore((s) => s.messages);
  const toolStatus = useChatStore((s) => s.toolStatus);
  const setCourseContext = useChatStore((s) => s.setCourseContext);
  const loadSessions = useChatStore((s) => s.loadSessions);
  const registerFallbackOnAction = useChatStore((s) => s.registerFallbackOnAction);
  const setSelectedNodeId = useWorkspaceStore((s) => s.setSelectedNodeId);
  const triggerRefresh = useWorkspaceStore((s) => s.triggerRefresh);

  // Set course context and load sessions on mount / courseId change.
  useEffect(() => {
    setCourseContext(courseId);
    void loadSessions(courseId, { restoreLatest: true });
  }, [courseId, setCourseContext, loadSessions]);

  // Fallback onAction handler (used when no page-level handler is registered):
  // refresh the workspace section a chat action touched.
  useEffect(() => {
    const blockTypeToSection = (blockType: string): SectionId => {
      if (blockType === "plan") return "plan";
      if (blockType === "progress" || blockType === "forecast") return "analytics";
      if (blockType === "quiz" || blockType === "flashcards" || blockType === "wrong_answers" || blockType === "review") {
        return "practice";
      }
      return "notes";
    };
    const isSection = (value: unknown): value is SectionId =>
      value === "notes" || value === "practice" || value === "analytics" || value === "plan";

    const handleAction = (action: ChatAction) => {
      const type = action.action;
      if (type === "data_updated") {
        if (isSection(action.value)) triggerRefresh(action.value);
        return;
      }

      if (type === "focus_topic") {
        if (action.value) setSelectedNodeId(action.value);
        return;
      }

      if (type === "set_learning_mode" || type === "suggest_mode") {
        triggerRefresh("plan");
        return;
      }

      if (type === "add_block" || type === "remove_block" || type === "resize_block") {
        const [blockType] = (action.value ?? "").split(":");
        triggerRefresh(blockTypeToSection(blockType));
        return;
      }

      if (type === "reorder_blocks" || type === "apply_template" || type === "agent_insight") {
        triggerRefresh("notes");
      }
    };

    return registerFallbackOnAction(handleAction);
  }, [registerFallbackOnAction, setSelectedNodeId, triggerRefresh]);

  return (
    <div role="region" aria-label="Chat" className="flex h-full flex-col bg-background/80">
      <ChatHeader courseId={courseId} />

      <MessageList messages={messages} />

      <ToolStatus status={toolStatus} />

      <GeneratedQuizCard courseId={courseId} />

      {!aiActionsEnabled ? <AiFeatureBlocked compact className="mx-3 mb-2" /> : null}

      <ChatInput courseId={courseId} disabled={!aiActionsEnabled} />
    </div>
  );
}
