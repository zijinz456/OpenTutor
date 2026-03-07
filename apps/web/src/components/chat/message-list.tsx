"use client";

import { useRef, useEffect, useCallback } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { MessageBubble } from "@/components/chat/message-bubble";
import { ClarifyCard } from "@/components/chat/clarify-card";
import { StreamingIndicator } from "@/components/chat/streaming-indicator";
import { useChatStore, type ChatMessage } from "@/store/chat";
import { MessageSquare } from "lucide-react";

interface MessageListProps {
  messages: ChatMessage[];
}

/**
 * Virtualized scrollable message list with auto-scroll-to-bottom.
 * Uses @tanstack/react-virtual for efficient rendering of long conversations.
 */
export function MessageList({ messages }: MessageListProps) {
  const parentRef = useRef<HTMLDivElement>(null);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const clarifyOptions = useChatStore((s) => s.clarifyOptions);
  const activeCourseId = useChatStore((s) => s.activeCourseId);

  // Extra items: clarify card + streaming indicator + bottom spacer
  const extraCount =
    (clarifyOptions && activeCourseId && !isStreaming ? 1 : 0) +
    (isStreaming ? 1 : 0);
  const totalCount = messages.length + extraCount;

  const virtualizer = useVirtualizer({
    count: totalCount,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 80,
    overscan: 5,
  });

  const scrollToBottom = useCallback(() => {
    if (totalCount > 0) {
      virtualizer.scrollToIndex(totalCount - 1, { align: "end", behavior: "smooth" });
    }
  }, [virtualizer, totalCount]);

  // Auto-scroll to bottom on new messages or clarify options.
  useEffect(() => {
    scrollToBottom();
  }, [messages.length, clarifyOptions, scrollToBottom]);

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
    <div ref={parentRef} className="flex-1 overflow-auto">
      <div
        className="relative w-full p-3"
        style={{ height: `${virtualizer.getTotalSize()}px` }}
      >
        {virtualizer.getVirtualItems().map((virtualItem) => {
          const index = virtualItem.index;

          let content: React.ReactNode;
          if (index < messages.length) {
            content = <MessageBubble key={messages[index].id} message={messages[index]} />;
          } else {
            const extraIndex = index - messages.length;
            const showClarify = clarifyOptions && activeCourseId && !isStreaming;
            if (showClarify && extraIndex === 0) {
              content = (
                <div className="flex justify-start mb-2">
                  <div className="max-w-[85%]">
                    <ClarifyCard clarify={clarifyOptions} courseId={activeCourseId} />
                  </div>
                </div>
              );
            } else if (isStreaming) {
              content = (
                <div className="flex justify-start">
                  <StreamingIndicator />
                </div>
              );
            }
          }

          return (
            <div
              key={virtualItem.key}
              data-index={virtualItem.index}
              ref={virtualizer.measureElement}
              className="absolute top-0 left-0 w-full"
              style={{ transform: `translateY(${virtualItem.start}px)` }}
            >
              {content}
            </div>
          );
        })}
      </div>
    </div>
  );
}
