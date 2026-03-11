"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Send, Loader2, Sparkles, ChevronRight } from "lucide-react";
import {
  FileText, HelpCircle, Layers, BarChart3, Brain, BookOpen,
  ListChecks, AlertTriangle, Lightbulb,
} from "lucide-react";
import { interviewTurn } from "@/lib/api/onboarding";
import type { SpaceLayoutResponse, OnboardingAction } from "@/lib/api/onboarding";

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

const BLOCK_NAMES: Record<string, string> = {
  notes: "笔记",
  quiz: "测验",
  flashcards: "闪卡",
  progress: "进度",
  knowledge_graph: "知识图谱",
  review: "复习",
  chapter_list: "章节",
  plan: "计划",
  wrong_answers: "错题本",
  forecast: "预测",
  agent_insight: "AI 洞察",
};

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface HabitInterviewStepProps {
  onComplete: (layout: SpaceLayoutResponse, profile: Record<string, unknown>) => void;
  onSkip: () => void;
  onBack: () => void;
  t: (key: string) => string;
}

export function HabitInterviewStep({ onComplete, onSkip, onBack, t }: HabitInterviewStepProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [partialProfile, setPartialProfile] = useState<Record<string, unknown>>({});
  const [recommendedLayout, setRecommendedLayout] = useState<SpaceLayoutResponse | null>(null);
  const [completeProfile, setCompleteProfile] = useState<Record<string, unknown> | null>(null);
  const [isTyping, setIsTyping] = useState(false);
  const [inputValue, setInputValue] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const initRef = useRef(false);

  // Auto-scroll to bottom
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, isTyping]);

  // Send opening message on mount
  useEffect(() => {
    if (initRef.current) return;
    initRef.current = true;
    void doSend("");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const doSend = useCallback(async (text: string) => {
    const newMessages: ChatMessage[] = text
      ? [...messages, { role: "user", content: text }]
      : [...messages];

    if (text) setMessages(newMessages);
    setIsTyping(true);
    setInputValue("");

    try {
      const history = newMessages.map((m) => ({ role: m.role, content: m.content }));
      const res = await interviewTurn({
        message: text,
        history,
        partial_profile: partialProfile,
      });

      if (res.profile) setPartialProfile(res.profile);

      setMessages([...newMessages, { role: "assistant", content: res.response }]);

      const layoutAction = res.actions?.find((a: OnboardingAction) => a.type === "recommend_layout");
      if (layoutAction?.layout) {
        setRecommendedLayout(layoutAction.layout);
        setCompleteProfile(res.profile);
      }
    } catch {
      setMessages([
        ...newMessages,
        { role: "assistant", content: "抱歉，出了点问题。你可以跳过这一步，手动选择模板。" },
      ]);
    } finally {
      setIsTyping(false);
    }
  }, [messages, partialProfile]);

  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    const text = inputValue.trim();
    if (!text || isTyping) return;
    void doSend(text);
  }, [inputValue, isTyping, doSend]);

  const handleAccept = useCallback(() => {
    if (recommendedLayout && completeProfile) {
      onComplete(recommendedLayout, completeProfile);
    }
  }, [recommendedLayout, completeProfile, onComplete]);

  return (
    <div className="flex flex-col" style={{ minHeight: 420 }}>
      {/* Header */}
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-foreground">
          {t("setup.interviewTitle") !== "setup.interviewTitle"
            ? t("setup.interviewTitle")
            : "告诉我你的学习方式"}
        </h2>
        <p className="text-sm text-muted-foreground mt-1">
          {t("setup.interviewDescription") !== "setup.interviewDescription"
            ? t("setup.interviewDescription")
            : "回答几个简单问题，我会为你推荐最适合的学习空间"}
        </p>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-3 mb-4 max-h-64 pr-1">
        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap ${
                msg.role === "user"
                  ? "bg-brand text-brand-foreground rounded-br-md"
                  : "bg-muted text-foreground rounded-bl-md"
              }`}
            >
              {msg.content}
            </div>
          </div>
        ))}
        {isTyping && (
          <div className="flex justify-start">
            <div className="bg-muted rounded-2xl rounded-bl-md px-4 py-2.5">
              <div className="flex gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/50 animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/50 animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/50 animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Layout Recommendation Card */}
      {recommendedLayout && (
        <div className="border rounded-xl p-5 mb-4 bg-card border-brand/30">
          <div className="flex items-center gap-2 mb-3">
            <Sparkles className="size-4 text-brand" />
            <p className="text-sm font-medium text-foreground">为你推荐的学习空间</p>
          </div>

          <div className={`grid gap-2 mb-4 ${recommendedLayout.columns === 3 ? "grid-cols-3" : "grid-cols-2"}`}>
            {recommendedLayout.blocks
              .filter((b) => b.type !== "chapter_list")
              .map((block, i) => {
                const Icon = BLOCK_ICONS[block.type] || BookOpen;
                const name = BLOCK_NAMES[block.type] || block.type;
                const span =
                  block.size === "large"
                    ? "col-span-2"
                    : block.size === "full"
                      ? `col-span-${recommendedLayout.columns}`
                      : "";
                return (
                  <div
                    key={i}
                    className={`flex items-center gap-2 p-2.5 rounded-lg bg-muted/50 border border-border/50 ${span}`}
                  >
                    <Icon className="size-3.5 text-muted-foreground shrink-0" />
                    <span className="text-xs text-foreground">{name}</span>
                    <span className="text-[10px] text-muted-foreground ml-auto">{block.size}</span>
                  </div>
                );
              })}
          </div>

          <div className="flex gap-2">
            <button
              type="button"
              onClick={handleAccept}
              className="flex-1 flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium rounded-lg bg-brand text-brand-foreground hover:opacity-90 transition-opacity"
            >
              开始学习
              <ChevronRight className="size-4" />
            </button>
            <button
              type="button"
              onClick={onSkip}
              className="px-4 py-2 text-sm rounded-lg border border-border text-muted-foreground hover:text-foreground hover:border-foreground/20 transition-colors"
            >
              手动调整
            </button>
          </div>
        </div>
      )}

      {/* Input area */}
      {!recommendedLayout && (
        <form onSubmit={handleSubmit} className="flex gap-2">
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="描述你的学习方式..."
            disabled={isTyping}
            className="flex-1 px-4 py-2.5 text-sm rounded-xl border border-border bg-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-brand/50 disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={!inputValue.trim() || isTyping}
            className="p-2.5 rounded-xl bg-brand text-brand-foreground hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isTyping ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
          </button>
        </form>
      )}

      {/* Footer navigation */}
      {!recommendedLayout && (
        <div className="flex items-center justify-between mt-3">
          <button
            type="button"
            onClick={onBack}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            {t("common.back") !== "common.back" ? t("common.back") : "返回"}
          </button>
          <button
            type="button"
            onClick={onSkip}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            {t("setup.interviewSkip") !== "setup.interviewSkip" ? t("setup.interviewSkip") : "跳过，手动选择模板"}
          </button>
        </div>
      )}
    </div>
  );
}
