"use client";

import { useRef, useEffect, useState } from "react";
import { Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useChatStore, type ChatMessage } from "@/store/chat";

/**
 * Chat Panel — AI conversation with SSE streaming.
 *
 * Phase 0-A: Basic streaming chat with RAG.
 * Phase 0-B: assistant-ui integration, tool-call rendering.
 * Reference: assistant-ui (assistant-ui/assistant-ui) for streaming UX.
 */

interface ChatPanelProps {
  courseId: string;
  activeTab?: string;
  scene?: string;
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-3`}>
      <div
        className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted"
        }`}
      >
        <div className="whitespace-pre-wrap">{message.content || (
          <span className="animate-pulse">Thinking...</span>
        )}</div>
      </div>
    </div>
  );
}

export function ChatPanel({ courseId, activeTab, scene }: ChatPanelProps) {
  const { messages, isStreaming, sendMessage } = useChatStore();
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput("");
    await sendMessage(courseId, text, { activeTab, scene });
  };

  return (
    <div className="flex-1 flex flex-col">
      {/* Messages */}
      <ScrollArea className="flex-1 p-3" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full min-h-[200px]">
            <div className="text-center">
              <p className="text-muted-foreground text-sm">Ask anything about your course</p>
              <p className="text-muted-foreground text-xs mt-1">
                AI will reference your uploaded materials
              </p>
            </div>
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
      </ScrollArea>

      {/* Input */}
      <div className="border-t p-3">
        <div className="flex gap-2">
          <Textarea
            placeholder="Ask about your course materials..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            className="min-h-[40px] max-h-[120px] resize-none"
            rows={1}
          />
          <Button
            size="icon"
            onClick={handleSend}
            disabled={isStreaming || !input.trim()}
          >
            <Send className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
