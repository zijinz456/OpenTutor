"use client";

import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/store/chat";
import { ActionCard } from "@/components/chat/action-card";

interface MessageBubbleProps {
  message: ChatMessage;
}

/**
 * Single message bubble.
 *
 * - User messages: right-aligned, chat-user colours.
 * - Assistant messages: left-aligned, chat-assistant colours with
 *   whitespace-pre-wrap (markdown renderer to be added later).
 * - Shows ActionCard components when metadata.actions is present.
 */
export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const actions = message.metadata?.actions;

  return (
    <div className={cn("flex mb-2", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-lg px-3 py-2 text-sm",
          isUser
            ? "bg-[var(--chat-user-bg,hsl(var(--primary)))] text-[var(--chat-user-fg,hsl(var(--primary-foreground)))]"
            : "bg-[var(--chat-assistant-bg,hsl(var(--muted)))] text-[var(--chat-assistant-fg,hsl(var(--foreground)))]",
        )}
      >
        {/* Message content */}
        {message.content ? (
          <div className="whitespace-pre-wrap break-words">{message.content}</div>
        ) : (
          <span className="text-xs italic opacity-60">...</span>
        )}

        {/* Action cards from metadata */}
        {!isUser && actions && actions.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {actions.map((action, i) => (
              <ActionCard
                key={`${action.action}-${i}`}
                action={{
                  type: action.action,
                  label: action.value ?? action.action,
                  payload: action.extra ? { extra: action.extra } : undefined,
                }}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
