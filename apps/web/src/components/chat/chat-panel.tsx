"use client";

import { useRef, useEffect, useState, useCallback } from "react";
import { Download, MessageSquarePlus, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useChatStore, type ChatMessage } from "@/store/chat";
import { useT } from "@/lib/i18n-context";
import {
  listGeneratedQuizBatches,
  parseGeneratedQuizDraft,
  saveGeneratedQuiz,
  type GeneratedQuizBatchSummary,
} from "@/lib/api";
import { toast } from "sonner";

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

function MessageBubble({
  message,
  courseId,
  latestBatch,
  onSaved,
}: {
  message: ChatMessage;
  courseId: string;
  latestBatch: GeneratedQuizBatchSummary | null;
  onSaved?: () => void;
}) {
  const isUser = message.role === "user";
  const t = useT();
  const [saving, setSaving] = useState(false);
  const generatedQuestions = !isUser ? parseGeneratedQuizDraft(message.content) : [];

  const handleSave = async (replaceBatchId?: string) => {
    setSaving(true);
    try {
      const result = await saveGeneratedQuiz(courseId, message.content, "AI Practice Set", replaceBatchId);
      toast.success(
        result.replaced
          ? `Replaced saved set with version ${result.version}`
          : `Saved ${result.saved} questions to the course quiz bank`,
      );
      onSaved?.();
    } catch (error) {
      toast.error((error as Error).message || "Failed to save generated questions");
    } finally {
      setSaving(false);
    }
  };

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
          <span className="animate-pulse">{t("chat.thinking")}</span>
        )}</div>
        {!isUser && generatedQuestions.length > 0 && (
          <div className="mt-3 flex items-center justify-between gap-2 border-t pt-2">
            <span className="text-xs text-muted-foreground">
              {generatedQuestions.length} generated questions detected
            </span>
            <div className="flex items-center gap-2">
              {latestBatch?.is_active && (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => handleSave(latestBatch.batch_id)}
                  disabled={saving}
                >
                  <Download className="h-4 w-4 mr-1" />
                  {saving ? "Saving..." : "Replace Latest"}
                </Button>
              )}
              <Button type="button" size="sm" variant="outline" onClick={() => handleSave()} disabled={saving}>
                <Download className="h-4 w-4 mr-1" />
                {saving ? "Saving..." : "Save New"}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function ChatPanel({ courseId, activeTab, scene }: ChatPanelProps) {
  const t = useT();
  const {
    messages,
    isStreaming,
    isLoadingSessions,
    toolStatus,
    sendMessage,
    setCourseContext,
    loadSessions,
    loadSessionMessages,
    loadSessions: refreshSessions,
    startNewSession,
    sessionIds,
    sessionsByCourse,
  } = useChatStore();
  const [input, setInput] = useState("");
  const [generatedBatches, setGeneratedBatches] = useState<GeneratedQuizBatchSummary[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const sessions = sessionsByCourse[courseId] ?? [];
  const currentSessionId = sessionIds[courseId] ?? "";
  const latestGeneratedBatch = generatedBatches.find((batch) => batch.is_active) ?? null;

  const loadGeneratedBatches = useCallback(async () => {
    try {
      setGeneratedBatches(await listGeneratedQuizBatches(courseId));
    } catch {
      setGeneratedBatches([]);
    }
  }, [courseId]);

  useEffect(() => {
    setCourseContext(courseId);
    void loadSessions(courseId, { restoreLatest: true });
    queueMicrotask(() => {
      void loadGeneratedBatches();
    });
  }, [courseId, loadGeneratedBatches, loadSessions, setCourseContext]);

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
      <div className="border-b p-3 flex items-center gap-2">
        <select
          data-testid="chat-session-select"
          className="h-9 flex-1 rounded-md border bg-background px-3 text-sm"
          value={currentSessionId}
          onChange={(e) => {
            const value = e.target.value;
            if (value) {
              void loadSessionMessages(courseId, value);
            }
          }}
          disabled={isStreaming || isLoadingSessions}
        >
          <option value="">Current conversation</option>
          {sessions.map((session) => (
            <option key={session.id} value={session.id}>
              {session.title}
            </option>
          ))}
        </select>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => startNewSession(courseId)}
          disabled={isStreaming}
        >
          <MessageSquarePlus className="h-4 w-4 mr-2" />
          New
        </Button>
      </div>

      {/* Messages */}
      <ScrollArea className="flex-1 p-3" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full min-h-[200px]">
            <div className="text-center">
              <p className="text-muted-foreground text-sm">
                {isLoadingSessions ? t("general.loading") : t("chat.empty")}
              </p>
              <p className="text-muted-foreground text-xs mt-1">
                AI will reference your uploaded materials
              </p>
            </div>
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            courseId={courseId}
            latestBatch={latestGeneratedBatch}
            onSaved={() => {
              void Promise.all([refreshSessions(courseId), loadGeneratedBatches()]);
            }}
          />
        ))}
      </ScrollArea>

      {/* Tool status indicator (ReAct agent tool execution) */}
      {toolStatus && (
        <div className="flex items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground bg-muted/50 border-t">
          {toolStatus.status === "running" ? (
            <>
              <span className="animate-spin h-3 w-3 border-2 border-primary border-t-transparent rounded-full inline-block" />
              <span>{toolStatus.tool.replace(/_/g, " ")}...</span>
            </>
          ) : (
            <span className="text-green-600">&#10003; {toolStatus.tool.replace(/_/g, " ")}</span>
          )}
        </div>
      )}

      {/* Input */}
      <div className="border-t p-3">
        <div className="flex gap-2">
          <Textarea
            data-testid="chat-input"
            placeholder={t("chat.placeholder")}
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
            data-testid="chat-send"
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
