"use client";

import { useChatStore } from "@/store/chat";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Plus } from "lucide-react";

interface ChatHeaderProps {
  courseId: string;
}

/**
 * Compact chat panel header with session selector and "New Chat" button.
 * Height ~36px.
 */
export function ChatHeader({ courseId }: ChatHeaderProps) {
  const sessionsByCourse = useChatStore((s) => s.sessionsByCourse);
  const sessionIds = useChatStore((s) => s.sessionIds);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const isLoadingSessions = useChatStore((s) => s.isLoadingSessions);
  const loadSessionMessages = useChatStore((s) => s.loadSessionMessages);
  const startNewSession = useChatStore((s) => s.startNewSession);

  const sessions = sessionsByCourse[courseId] ?? [];
  const currentSessionId = sessionIds[courseId] ?? "";

  const formatSessionLabel = (session: (typeof sessions)[number], index: number) => {
    if (session.title) return session.title;
    const date = session.created_at
      ? new Date(session.created_at).toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
        })
      : "";
    return `Session ${index + 1}${date ? ` - ${date}` : ""}`;
  };

  return (
    <div role="banner" aria-label="Chat header" className="flex h-10 shrink-0 items-center gap-2 border-b border-border/40 px-4">
      <Select
        value={currentSessionId || "__current__"}
        onValueChange={(value) => {
          if (value && value !== "__current__") {
            void loadSessionMessages(courseId, value);
          }
        }}
        disabled={isStreaming || isLoadingSessions}
      >
        <SelectTrigger
          size="sm"
          className="h-7 min-w-[160px] flex-1 text-xs"
          data-testid="chat-session-select"
          aria-label="Select chat session"
        >
          <SelectValue placeholder="Current conversation" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="__current__">Current conversation</SelectItem>
          {sessions.map((session, i) => (
            <SelectItem key={session.id} value={session.id}>
              {formatSessionLabel(session, i)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => startNewSession(courseId)}
        disabled={isStreaming}
        title="New Chat"
        aria-label="Start new chat session"
      >
        <Plus className="mr-1 size-3.5" />
        New
      </Button>
    </div>
  );
}
