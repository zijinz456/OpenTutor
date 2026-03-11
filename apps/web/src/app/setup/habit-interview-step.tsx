"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  BookOpen,
  Brain,
  BarChart3,
  ListChecks,
  HelpCircle,
  Layers,
  AlertTriangle,
  Lightbulb,
  FileText,
  ArrowLeft,
  ArrowRight,
  Loader2,
} from "lucide-react";
import { API_BASE } from "@/lib/api/client";
import { buildAuthHeaders } from "@/lib/auth";

// ── Types ──

export interface RecommendedLayout {
  blocks: Array<{
    type: string;
    size: string;
    config: Record<string, unknown>;
    position: number;
    visible: boolean;
    source: string;
  }>;
  columns: number;
  mode: string;
  templateId: string | null;
}

export interface ProfileSummary {
  style: string;
  pattern: string;
  duration: string;
}

interface HabitInterviewStepProps {
  onComplete: (layout: RecommendedLayout) => void;
  onSkip: () => void;
  onBack: () => void;
  t: (key: string) => string;
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

// ── Block icon mapping (matches template-step.tsx) ──

const BLOCK_ICONS: Record<string, typeof BookOpen> = {
  notes: FileText,
  quiz: HelpCircle,
  flashcards: Layers,
  progress: BarChart3,
  knowledge_graph: Brain,
  review: BookOpen,
  chapter_list: ListChecks,
  plan: ListChecks,
  wrong_answers: AlertTriangle,
  forecast: BarChart3,
  agent_insight: Lightbulb,
};

// ── SSE streaming helper ──

interface OnboardingStreamOptions {
  message: string;
  history: Array<{ role: string; content: string }>;
  partialProfile?: Record<string, unknown> | null;
  signal?: AbortSignal;
}

interface OnboardingEvent {
  event: string;
  data: Record<string, unknown>;
}

async function* streamOnboardingInterview(
  opts: OnboardingStreamOptions,
): AsyncGenerator<OnboardingEvent, void, unknown> {
  const res = await fetch(`${API_BASE}/onboarding/interview`, {
    method: "POST",
    headers: buildAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      message: opts.message,
      history: opts.history,
      partial_profile: opts.partialProfile ?? null,
    }),
    signal: opts.signal,
  });

  if (!res.ok || !res.body) {
    throw new Error("Interview stream failed");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });

    let idx = buffer.indexOf("\n\n");
    while (idx !== -1) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);

      let eventName = "message";
      const dataLines: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) eventName = line.slice(7).trim();
        else if (line.startsWith("data: ")) dataLines.push(line.slice(6));
      }

      if (dataLines.length) {
        try {
          const data = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
          yield { event: eventName, data };
        } catch {
          // skip malformed JSON
        }
      }

      idx = buffer.indexOf("\n\n");
    }

    if (done) break;
  }
}

// ── Component ──

export function HabitInterviewStep({
  onComplete,
  onSkip,
  onBack,
  t,
}: HabitInterviewStepProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [partialProfile, setPartialProfile] = useState<Record<string, unknown> | null>(null);
  const [recommendedLayout, setRecommendedLayout] = useState<RecommendedLayout | null>(null);
  const [profileSummary, setProfileSummary] = useState<ProfileSummary | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const startedRef = useRef(false);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isStreaming]);

  // Start the interview on mount by sending an empty message
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    void sendMessage("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sendMessage = useCallback(
    async (text: string) => {
      // Add user message to chat (skip for initial empty message)
      const updatedMessages: ChatMessage[] =
        text.trim()
          ? [...messages, { role: "user" as const, content: text }]
          : [...messages];

      if (text.trim()) {
        setMessages(updatedMessages);
      }
      setInput("");
      setIsStreaming(true);

      const controller = new AbortController();
      abortRef.current = controller;

      let assistantContent = "";

      try {
        const gen = streamOnboardingInterview({
          message: text,
          history: updatedMessages.map((m) => ({ role: m.role, content: m.content })),
          partialProfile,
          signal: controller.signal,
        });

        // Add an empty assistant message to stream into
        const withAssistant: ChatMessage[] = [
          ...updatedMessages,
          { role: "assistant", content: "" },
        ];
        setMessages(withAssistant);

        for await (const evt of gen) {
          if (evt.event === "message" && typeof evt.data.content === "string") {
            assistantContent += evt.data.content;
            setMessages([
              ...updatedMessages,
              { role: "assistant", content: assistantContent },
            ]);
          } else if (evt.event === "replace" && typeof evt.data.content === "string") {
            assistantContent = evt.data.content;
            setMessages([
              ...updatedMessages,
              { role: "assistant", content: assistantContent },
            ]);
          } else if (evt.event === "profile_update" && evt.data.partial_profile) {
            setPartialProfile(evt.data.partial_profile as Record<string, unknown>);
          } else if (evt.event === "done") {
            if (evt.data.partial_profile) {
              setPartialProfile(evt.data.partial_profile as Record<string, unknown>);
            }
            if (evt.data.onboarding_complete && evt.data.recommended_layout) {
              const layout = evt.data.recommended_layout as RecommendedLayout;
              setRecommendedLayout(layout);
              if (evt.data.profile_summary) {
                setProfileSummary(evt.data.profile_summary as ProfileSummary);
              }
            }
          }
        }
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          // Show error as assistant message
          setMessages([
            ...updatedMessages,
            {
              role: "assistant",
              content: assistantContent || "Something went wrong. Please try again.",
            },
          ]);
        }
      } finally {
        setIsStreaming(false);
        abortRef.current = null;
      }
    },
    [messages, partialProfile],
  );

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (!input.trim() || isStreaming) return;
      void sendMessage(input.trim());
    },
    [input, isStreaming, sendMessage],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (!input.trim() || isStreaming) return;
        void sendMessage(input.trim());
      }
    },
    [input, isStreaming, sendMessage],
  );

  // Clean up on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  return (
    <div className="flex flex-col gap-4 animate-in fade-in slide-in-from-bottom-3 duration-300">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold text-foreground">
          {t("setup.interviewTitle")}
        </h2>
        <p className="text-sm text-muted-foreground mt-1">
          {t("setup.interviewDescription")}
        </p>
      </div>

      {/* Chat area */}
      <div className="flex flex-col gap-3 min-h-[240px] max-h-[400px] overflow-y-auto rounded-xl border border-border bg-card p-4">
        {messages.map((msg, i) =>
          msg.role === "assistant" ? (
            <div key={i} className="flex justify-start">
              <div className="bg-muted/50 rounded-2xl rounded-tl-sm p-3 max-w-[85%] text-sm text-foreground whitespace-pre-wrap">
                {msg.content || (
                  <span className="text-muted-foreground italic">
                    {t("setup.interviewSending")}
                  </span>
                )}
              </div>
            </div>
          ) : (
            <div key={i} className="flex justify-end">
              <div className="bg-brand/10 rounded-2xl rounded-tr-sm p-3 max-w-[85%] text-sm text-foreground whitespace-pre-wrap ml-auto">
                {msg.content}
              </div>
            </div>
          ),
        )}

        {/* Streaming indicator */}
        {isStreaming && messages.length > 0 && messages[messages.length - 1]?.role !== "assistant" && (
          <div className="flex justify-start">
            <div className="bg-muted/50 rounded-2xl rounded-tl-sm p-3 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Recommended layout preview (shown when interview is complete) */}
      {recommendedLayout && (
        <div className="rounded-xl border border-brand/30 bg-brand-muted/10 p-4 space-y-3">
          {profileSummary && (
            <div className="flex flex-wrap gap-2 text-xs">
              <span className="px-2 py-0.5 rounded bg-muted text-muted-foreground">
                {profileSummary.style}
              </span>
              <span className="px-2 py-0.5 rounded bg-muted text-muted-foreground">
                {profileSummary.pattern}
              </span>
              <span className="px-2 py-0.5 rounded bg-muted text-muted-foreground">
                {profileSummary.duration}
              </span>
            </div>
          )}

          {/* Block grid preview */}
          <div className="grid grid-cols-3 gap-1.5">
            {recommendedLayout.blocks
              .filter((b) => b.visible)
              .map((block, i) => {
                const Icon = BLOCK_ICONS[block.type] ?? BookOpen;
                const colSpan =
                  block.size === "large"
                    ? "col-span-2"
                    : block.size === "full"
                      ? "col-span-3"
                      : "";
                return (
                  <div
                    key={i}
                    className={`flex items-center gap-1.5 rounded-lg bg-muted/60 px-2 py-1.5 ${colSpan}`}
                    title={block.type.replace(/_/g, " ")}
                  >
                    <Icon className="size-3.5 text-muted-foreground shrink-0" />
                    <span className="text-[11px] text-muted-foreground truncate">
                      {block.type.replace(/_/g, " ")}
                    </span>
                  </div>
                );
              })}
          </div>

          {/* Accept / Adjust buttons */}
          <div className="flex items-center gap-3 pt-1">
            <button
              type="button"
              onClick={() => onComplete(recommendedLayout)}
              className="px-5 py-2 text-sm font-medium rounded-lg bg-brand text-brand-foreground hover:opacity-90 transition-opacity"
            >
              {t("setup.interviewAccept")}
            </button>
            <button
              type="button"
              onClick={onSkip}
              className="px-4 py-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              {t("setup.interviewAdjust")}
            </button>
          </div>
        </div>
      )}

      {/* Input area (hidden when layout recommendation is shown) */}
      {!recommendedLayout && (
        <form onSubmit={handleSubmit} className="flex items-center gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isStreaming}
            placeholder={t("setup.interviewPlaceholder")}
            className="flex-1 h-10 px-3 border border-border rounded-lg bg-background text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-brand/20 disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={!input.trim() || isStreaming}
            className="h-10 w-10 flex items-center justify-center rounded-lg bg-brand text-brand-foreground hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
          >
            {isStreaming ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <ArrowRight className="size-4" />
            )}
          </button>
        </form>
      )}

      {/* Footer navigation */}
      <div className="flex items-center justify-between pt-1">
        <button
          type="button"
          onClick={onBack}
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="size-3.5" />
          {t("common.back")}
        </button>
        {!recommendedLayout && (
          <button
            type="button"
            onClick={onSkip}
            className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            {t("setup.interviewSkip")}
            <ArrowRight className="size-3.5" />
          </button>
        )}
      </div>
    </div>
  );
}
