"use client";

import { useRef, useEffect } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { MessageBubble } from "@/components/chat/message-bubble";
import { StreamingIndicator } from "@/components/chat/streaming-indicator";
import { useChatStore, type ChatMessage } from "@/store/chat";
import { MessageSquare } from "lucide-react";

interface MessageListProps {
  messages: ChatMessage[];
}

/**
 * Scrollable message list with auto-scroll-to-bottom on new messages.
 * Shows an empty state when no messages are present.
 */
export function MessageList({ messages }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const isStreaming = useChatStore((s) => s.isStreaming);

  // Auto-scroll to bottom whenever messages change or during streaming.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="text-center">
          <MessageSquare className="mx-auto mb-2 size-8 text-muted-foreground/40" />
          <p className="text-sm text-muted-foreground">
            No messages yet
          </p>
          <p className="mt-1 text-xs text-muted-foreground/70">
            AI will reference your uploaded materials while answering
          </p>
        </div>
      </div>
    );
  }

  return (
    <ScrollArea className="flex-1 overflow-hidden">
      <div className="space-y-1 p-3">
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {isStreaming && (
          <div className="flex justify-start">
            <StreamingIndicator />
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </ScrollArea>
  );
}
