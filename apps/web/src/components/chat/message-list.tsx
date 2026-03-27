"use client";

import { useRef, useEffect, useCallback } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { MessageBubble } from "@/components/chat/message-bubble";
import { ClarifyCard } from "@/components/chat/clarify-card";
import { StreamingIndicator } from "@/components/chat/streaming-indicator";
import { useChatStore, type ChatMessage } from "@/store/chat";
import { useT } from "@/lib/i18n-context";
import { MessageSquare, AlertCircle, AlertTriangle, RotateCcw } from "lucide-react";

interface MessageListProps {
  messages: ChatMessage[];
}

/**
 * Virtualized scrollable message list with auto-scroll-to-bottom.
 * Uses @tanstack/react-virtual for efficient rendering of long conversations.
 */
export function MessageList({ messages }: MessageListProps) {
  const t = useT();
  const parentRef = useRef<HTMLDivElement>(null);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const clarifyOptions = useChatStore((s) => s.clarifyOptions);
  const activeCourseId = useChatStore((s) => s.activeCourseId);
  const error = useChatStore((s) => s.error);
  const errorCategory = useChatStore((s) => s.errorCategory);
  const isMockLlm = useChatStore((s) => s.isMockLlm);
  const streamPhase = useChatStore((s) => s.streamPhase);
  const slowState = useChatStore((s) => s.slowState);
  const latestWarning = useChatStore((s) => s.latestWarning);

  const errorLabels: Record<string, string> = {
    rate_limit: t("chat.error.rateLimit"),
    auth_error: t("chat.error.authError"),
    timeout: t("chat.error.timeout"),
    llm_unavailable: t("chat.error.llmUnavailable"),
    generic: t("chat.error.generic"),
  };
  const phaseLabels: Record<string, string> = {
    routing: t("chat.status.routing"),
    loading: t("chat.status.loading"),
    generating: t("chat.status.generating"),
    verifying: t("chat.status.verifying"),
  };
  const slowHint =
    slowState === "analyzing"
      ? t("chat.slow.analyzing")
      : slowState === "delayed"
        ? t("chat.slow.delayed")
        : null;
  const showWarningBanner =
    latestWarning &&
    ["adaptation_degraded", "verification_skipped", "slow_response"].includes(latestWarning.type);

  // Extra items: clarify card + streaming indicator + bottom spacer
  const extraCount =
    (clarifyOptions && activeCourseId && !isStreaming ? 1 : 0) +
    (isStreaming ? 1 : 0);
  const totalCount = messages.length + extraCount;

  // eslint-disable-next-line react-hooks/incompatible-library
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
      <div role="status" aria-label="No messages" className="flex flex-1 items-center justify-center p-6 animate-fade-in">
        <div className="text-center">
          <MessageSquare className="mx-auto mb-3 size-8 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">
            {t("chat.noMessages")}
          </p>
          <p className="mt-1 text-xs text-muted-foreground/70">
            {t("chat.aiReference")}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div ref={parentRef} className="flex-1 overflow-auto scrollbar-thin" role="log" aria-live="polite" aria-relevant="additions" aria-label="Chat messages">
      {isMockLlm && (
        <div role="status" className="sticky top-0 z-10 flex items-center gap-2 bg-warning/10 border-b border-warning/30 px-3 py-1.5 text-xs text-warning">
          <AlertTriangle className="size-3.5 shrink-0" />
          <span>{t("chat.mockWarning")}</span>
        </div>
      )}
      {showWarningBanner ? (
        <div role="status" className="sticky top-0 z-10 flex items-center gap-2 bg-warning/10 border-b border-warning/30 px-3 py-1.5 text-xs text-warning">
          <AlertTriangle className="size-3.5 shrink-0" />
          <span>{latestWarning.message}</span>
        </div>
      ) : null}
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
                  <StreamingIndicator
                    phaseLabel={streamPhase ? phaseLabels[streamPhase] ?? streamPhase : null}
                    hint={slowHint}
                  />
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

      {/* Error banner with retry */}
      {error && !isStreaming && (
        <div role="alert" className="sticky bottom-0 mx-3 mb-2 flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive animate-fade-in">
          <AlertCircle className="size-4 shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="font-medium">{errorLabels[errorCategory ?? "generic"]}</p>
            {errorCategory === "generic" && error !== errorLabels.generic && (
              <p className="mt-0.5 opacity-70 truncate">{error}</p>
            )}
          </div>
          {activeCourseId && messages.length > 0 && (
            <button
              type="button"
              onClick={() => {
                const lastUserMsg = [...messages].reverse().find((m) => m.role === "user");
                if (lastUserMsg && activeCourseId) {
                  useChatStore.getState().sendMessage(activeCourseId, lastUserMsg.content, {
                    images: lastUserMsg.images,
                  });
                }
              }}
              className="flex items-center gap-1 rounded-md border border-destructive/30 px-2 py-1 text-xs font-medium hover:bg-destructive/10 transition-colors shrink-0"
              aria-label={t("chat.retryLabel")}
            >
              <RotateCcw className="size-3" />
              {t("common.retry")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
