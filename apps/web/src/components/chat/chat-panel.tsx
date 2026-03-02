"use client";

import Image from "next/image";
import { useRef, useEffect, useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { useChatStore, type ChatMessage } from "@/store/chat";
import { useT } from "@/lib/i18n-context";
import {
  listGeneratedQuizBatches,
  parseGeneratedQuizDraft,
  saveGeneratedQuiz,
  type ChatMessageMetadata,
  type GeneratedQuizBatchSummary,
  type ImageAttachment,
} from "@/lib/api";
import { toast } from "sonner";
import { MarkdownRenderer } from "@/components/course/markdown-renderer";
import { ProvenanceBadges } from "@/components/provenance-badges";
import { LlmStatusBanner } from "@/components/chat/llm-status-banner";

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

function ExplainableTrace({ metadata }: { metadata: ChatMessageMetadata }) {
  const provenance = metadata.provenance;
  if (!provenance) return null;

  const hasDetails = Boolean(
    provenance.scene_resolution?.reason ||
    provenance.scene_switch?.reason ||
    provenance.preference_details?.length ||
    provenance.content_refs?.length ||
    provenance.tool_names?.length ||
    metadata.verifier ||
    metadata.task_link,
  );

  if (!hasDetails) return null;

  return (
    <details className="mt-2 rounded-md border border-border/60 bg-background/60 px-2 py-1.5 text-xs text-muted-foreground">
      <summary className="cursor-pointer select-none font-medium text-foreground/80">
        Why this answer
      </summary>
      <div className="mt-2 space-y-2">
        {provenance.scene_switch?.reason && (
          <div>
            <p className="font-medium text-foreground/80">Scene suggestion</p>
            <p>{provenance.scene_switch.reason}</p>
            {provenance.scene_switch.expected_benefit && (
              <p className="mt-1">Benefit: {provenance.scene_switch.expected_benefit}</p>
            )}
            {provenance.scene_switch.reversible_action && (
              <p className="mt-1">Reversible: {provenance.scene_switch.reversible_action}</p>
            )}
          </div>
        )}
        {provenance.scene_resolution?.reason && (
          <div>
            <p className="font-medium text-foreground/80">Current mode</p>
            <p>{provenance.scene_resolution.reason}</p>
            {provenance.scene_resolution.expected_benefit && (
              <p className="mt-1">Benefit: {provenance.scene_resolution.expected_benefit}</p>
            )}
          </div>
        )}
        {provenance.preference_details && provenance.preference_details.length > 0 && (
          <div>
            <p className="font-medium text-foreground/80">Preferences applied</p>
            <ul className="list-disc pl-4">
              {provenance.preference_details.slice(0, 4).map((detail) => (
                <li key={`${detail.dimension}-${detail.value}`}>
                  {detail.dimension}: {detail.value} via {detail.source}
                </li>
              ))}
            </ul>
          </div>
        )}
        {provenance.content_refs && provenance.content_refs.length > 0 && (
          <div>
            <p className="font-medium text-foreground/80">Materials consulted</p>
            <ul className="list-disc pl-4">
              {provenance.content_refs.map((ref, index) => (
                <li key={`${ref.title || "ref"}-${index}`}>
                  {ref.title || "Untitled material"}
                  {ref.source_type ? ` (${ref.source_type})` : ""}
                  {ref.preview ? `: ${ref.preview}` : ""}
                </li>
              ))}
            </ul>
          </div>
        )}
        {provenance.tool_names && provenance.tool_names.length > 0 && (
          <div>
            <p className="font-medium text-foreground/80">Tools used</p>
            <p>{provenance.tool_names.join(", ")}</p>
          </div>
        )}
        {metadata.verifier && (
          <div>
            <p className="font-medium text-foreground/80">Verifier</p>
            <p>
              {metadata.verifier.status}: {metadata.verifier.message}
            </p>
          </div>
        )}
        {metadata.task_link && (
          <div>
            <p className="font-medium text-foreground/80">Background task</p>
            <p>
              {metadata.task_link.task_type} · {metadata.task_link.status} · {metadata.task_link.task_id}
            </p>
          </div>
        )}
      </div>
    </details>
  );
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
        data-testid={`chat-message-${message.role}`}
        data-role={message.role}
        className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted"
        }`}
      >
        {message.content ? (
          isUser ? (
            <div className="whitespace-pre-wrap">{message.content}</div>
          ) : (
            <MarkdownRenderer content={message.content} className="prose-sm prose-compact [&>*:first-child]:mt-0 [&>*:last-child]:mb-0" />
          )
        ) : (
          <span className="animate-pulse">{t("chat.thinking")}</span>
        )}
        {!isUser && message.metadata && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {message.metadata.agent && <Badge variant="outline">{message.metadata.agent}</Badge>}
            {message.metadata.intent && <Badge variant="outline">{message.metadata.intent}</Badge>}
            {typeof message.metadata.tokens === "number" && message.metadata.tokens > 0 && (
              <Badge variant="outline">{message.metadata.tokens} tok</Badge>
            )}
          </div>
        )}
        {!isUser && <ProvenanceBadges provenance={message.metadata?.provenance} compact />}
        {!isUser && message.metadata && <ExplainableTrace metadata={message.metadata} />}
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
                  <span className="mr-1 text-xs">Save</span>
                  {saving ? "Saving..." : "Replace Latest"}
                </Button>
              )}
              <Button type="button" size="sm" variant="outline" onClick={() => handleSave()} disabled={saving}>
                <span className="mr-1 text-xs">Save</span>
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
    error: chatError,
    toolStatus,
    sendMessage,
    setCourseContext,
    loadSessions,
    loadSessionMessages,
    loadSessions: refreshSessions,
    startNewSession,
    sessionIds,
    sessionsByCourse,
    activePlan,
  } = useChatStore();
  const [input, setInput] = useState("");
  const [imageAttachments, setImageAttachments] = useState<ImageAttachment[]>([]);
  const [generatedBatches, setGeneratedBatches] = useState<GeneratedQuizBatchSummary[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
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

  const handleImageSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    const MAX_IMAGES = 4;
    const remaining = MAX_IMAGES - imageAttachments.length;
    const toProcess = Array.from(files).slice(0, remaining);

    for (const file of toProcess) {
      if (!file.type.startsWith("image/")) continue;
      if (file.size > 10 * 1024 * 1024) {
        toast.error("Image must be under 10MB");
        continue;
      }
      const base64 = await new Promise<string>((resolve) => {
        const reader = new FileReader();
        reader.onload = () => {
          const result = reader.result as string;
          resolve(result.split(",")[1]); // strip data:...;base64, prefix
        };
        reader.readAsDataURL(file);
      });
      setImageAttachments((prev) => [
        ...prev,
        { data: base64, media_type: file.type, filename: file.name },
      ]);
    }
    // Reset input so same file can be re-selected
    e.target.value = "";
  }, [imageAttachments.length]);

  const removeImage = useCallback((index: number) => {
    setImageAttachments((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const handleSend = async () => {
    const text = input.trim();
    if (!text && imageAttachments.length === 0) return;
    const images = imageAttachments.length > 0 ? [...imageAttachments] : undefined;
    setInput("");
    setImageAttachments([]);
    await sendMessage(courseId, text || "Please analyze this image.", { activeTab, scene, images });
  };

  return (
    <div className="flex-1 flex flex-col">
      <LlmStatusBanner />
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
          + New
        </Button>
      </div>

      {/* Messages */}
      <ScrollArea className="flex-1 p-3" ref={scrollRef}>
        {activePlan && activePlan.steps.length > 0 && (
          <div className="mb-3 rounded-lg border border-primary/20 bg-primary/5 p-3 text-sm">
            <div className="flex items-start gap-2">
              <span className="mt-0.5 text-primary font-medium text-xs">Plan</span>
              <div className="min-w-0 flex-1">
                <p className="font-medium text-foreground">Background plan running</p>
                {activePlan.message && (
                  <p className="mt-1 text-xs text-muted-foreground">{activePlan.message}</p>
                )}
                <div className="mt-2 space-y-1.5">
                  {activePlan.steps.map((step) => {
                    const statusIndicator =
                      step.status === "completed"
                        ? "\u2713"
                        : step.status === "failed"
                          ? "\u2717"
                          : "\u2022";
                    const colorClass =
                      step.status === "completed"
                        ? "text-green-600"
                        : step.status === "failed"
                          ? "text-red-600"
                          : "text-muted-foreground";
                    return (
                      <div key={`${activePlan.taskId}-${step.step_index}`} className="flex items-start gap-2 text-xs">
                        <span className={`mt-0.5 font-bold ${colorClass}`}>{statusIndicator}</span>
                        <div className="min-w-0 flex-1">
                          <p className="font-medium text-foreground/90">{step.title}</p>
                          <p className="text-muted-foreground">
                            {step.status}
                            {step.summary ? ` \u2022 ${step.summary}` : ""}
                          </p>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        )}
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

      {/* Streaming / connection error with degradation suggestions */}
      {chatError && !isStreaming && (
        <div className="border-t bg-destructive/5 px-3 py-3">
          <div className="flex items-start gap-2 text-sm">
            <span className="text-destructive shrink-0 mt-0.5 font-bold text-xs">Warning</span>
            <div className="flex-1 min-w-0">
              <p className="font-medium text-destructive text-xs">
                {useChatStore.getState().errorCategory === "rate_limit"
                  ? "Rate limit reached -- try again in a moment"
                  : useChatStore.getState().errorCategory === "auth_error"
                    ? "API key issue -- check Settings"
                    : useChatStore.getState().errorCategory === "timeout"
                      ? "Request timed out -- try a shorter question"
                      : "AI service temporarily unavailable"}
              </p>
              <p className="text-[11px] text-muted-foreground mt-1 truncate">{chatError}</p>
              <div className="flex gap-2 mt-2">
                <Button type="button" variant="outline" size="sm" className="h-7 text-xs"
                  onClick={() => useChatStore.getState().onAction?.({ action: "set_layout_preset", value: "quizFocused" })}>
                  Quiz
                </Button>
                <Button type="button" variant="outline" size="sm" className="h-7 text-xs"
                  onClick={() => useChatStore.getState().onAction?.({ action: "set_layout_preset", value: "quizFocused" })}>
                  Flashcards
                </Button>
                <Button type="button" variant="outline" size="sm" className="h-7 text-xs"
                  onClick={() => useChatStore.getState().onAction?.({ action: "set_layout_preset", value: "notesFocused" })}>
                  Notes
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tool status indicator (ReAct agent tool execution) */}
      {toolStatus && (
        <div className="flex items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground bg-muted/50 border-t">
          {toolStatus.status === "running" ? (
            <>
              <span className="animate-spin h-3 w-3 border-2 border-primary border-t-transparent rounded-full inline-block" />
              <span>{toolStatus.explanation || toolStatus.tool.replace(/_/g, " ")}...</span>
            </>
          ) : (
            <span className="text-green-600">&#10003; {toolStatus.explanation || toolStatus.tool.replace(/_/g, " ")}</span>
          )}
        </div>
      )}

      {/* Input */}
      <div className="border-t p-3">
        {/* Image attachment previews */}
        {imageAttachments.length > 0 && (
          <div className="flex gap-2 mb-2 flex-wrap">
            {imageAttachments.map((img, i) => (
              <div key={i} className="relative group">
                <Image
                  src={`data:${img.media_type};base64,${img.data}`}
                  alt={img.filename || "attachment"}
                  width={64}
                  height={64}
                  unoptimized
                  className="h-16 w-16 object-cover rounded-md border"
                />
                <button
                  type="button"
                  title="Remove image"
                  onClick={() => removeImage(i)}
                  className="absolute -top-1.5 -right-1.5 bg-destructive text-destructive-foreground rounded-full w-4 h-4 flex items-center justify-center text-[10px] leading-none opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  x
                </button>
              </div>
            ))}
          </div>
        )}
        <div className="flex gap-2">
          <input
            ref={imageInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            multiple
            onChange={handleImageSelect}
            className="hidden"
            aria-label="Upload images"
          />
          <Button
            type="button"
            variant="outline"
            size="icon"
            onClick={() => imageInputRef.current?.click()}
            disabled={isStreaming || imageAttachments.length >= 4}
            title="Attach image"
          >
            <span className="text-xs">Img</span>
          </Button>
          <Textarea
            data-testid="chat-input"
            placeholder={imageAttachments.length > 0 ? "Describe what you need help with..." : t("chat.placeholder")}
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
            disabled={!input.trim() && imageAttachments.length === 0}
            title={isStreaming ? "Interrupt and send" : "Send message"}
            variant={isStreaming ? "destructive" : "default"}
          >
            {isStreaming ? <span className="text-xs">{"\u25B6"}</span> : <span className="text-xs">Send</span>}
          </Button>
        </div>
      </div>
    </div>
  );
}
