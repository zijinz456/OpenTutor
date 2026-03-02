"use client";

import { useEffect } from "react";
import { useChatStore } from "@/store/chat";
import { useWorkspaceStore, type SectionId } from "@/store/workspace";
import { useSceneStore } from "@/store/scene";
import { ChatHeader } from "@/components/chat/chat-header";
import { MessageList } from "@/components/chat/message-list";
import { ChatInput } from "@/components/chat/chat-input";
import { ToolStatus } from "@/components/chat/tool-status";
import type { ChatAction } from "@/lib/api";

interface ChatViewProps {
  courseId: string;
}

/**
 * Main chat container.
 *
 * Sits at the bottom of the workspace (full width, like a VS Code terminal
 * panel). Layout: header + message list + tool-status bar + input bar.
 */
export function ChatView({ courseId }: ChatViewProps) {
  const messages = useChatStore((s) => s.messages);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const toolStatus = useChatStore((s) => s.toolStatus);
  const setCourseContext = useChatStore((s) => s.setCourseContext);
  const loadSessions = useChatStore((s) => s.loadSessions);
  const setOnAction = useChatStore((s) => s.setOnAction);
  const setActiveSection = useWorkspaceStore((s) => s.setActiveSection);

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
    };

    setOnAction(handleAction);
  }, [setOnAction, setActiveSection]);

  return (
    <div className="flex h-full flex-col bg-background">
      <ChatHeader courseId={courseId} />

      <MessageList messages={messages} />

      <ToolStatus status={toolStatus} />

      <ChatInput courseId={courseId} disabled={false} />
    </div>
  );
}
