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
  const setActiveSection = useWorkspaceStore((s) => s.setActiveSection);
  const setSelectedNodeId = useWorkspaceStore((s) => s.setSelectedNodeId);
  const triggerRefresh = useWorkspaceStore((s) => s.triggerRefresh);

  // Set course context and load sessions on mount / courseId change.
  useEffect(() => {
    setCourseContext(courseId);
    void loadSessions(courseId, { restoreLatest: true });
  }, [courseId, setCourseContext, loadSessions]);

  // Register the onAction handler to bridge chat actions to workspace sections.
  useEffect(() => {
    const blockTypeToSection = (blockType: string): SectionId => {
      if (blockType === "plan") return "plan";
      if (blockType === "progress" || blockType === "forecast") return "analytics";
      if (blockType === "quiz" || blockType === "flashcards" || blockType === "wrong_answers" || blockType === "review") {
        return "practice";
      }
      return "notes";
    };

    const handleAction = (action: ChatAction) => {
      const type = action.action;
      if (type === "data_updated") {
        const section = action.value as SectionId | undefined;
        if (section) {
          triggerRefresh(section);
          setActiveSection(section);
        }
        return;
      }

      if (type === "focus_topic") {
        const nodeId = action.value;
        if (nodeId) {
          setSelectedNodeId(nodeId);
          setActiveSection("notes");
        }
        return;
      }

      if (type === "set_learning_mode" || type === "suggest_mode") {
        setActiveSection("plan");
        triggerRefresh("plan");
        return;
      }

      if (type === "add_block" || type === "remove_block") {
        const [blockType] = (action.value ?? "").split(":");
        const section = blockTypeToSection(blockType);
        setActiveSection(section);
        triggerRefresh(section);
        return;
      }

      if (type === "resize_block") {
        const [blockType] = (action.value ?? "").split(":");
        const section = blockTypeToSection(blockType);
        setActiveSection(section);
        triggerRefresh(section);
        return;
      }

      if (type === "reorder_blocks" || type === "apply_template" || type === "agent_insight") {
        setActiveSection("notes");
        triggerRefresh("notes");
      }
    };

    return registerFallbackOnAction(handleAction);
  }, [registerFallbackOnAction, setActiveSection, setSelectedNodeId, triggerRefresh]);

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
