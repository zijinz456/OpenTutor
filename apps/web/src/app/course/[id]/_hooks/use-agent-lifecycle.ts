"use client";

import { useEffect } from "react";
import { useChatStore } from "@/store/chat";
import type { ChatAction } from "@/lib/api";

const VALID_CHAT_ACTION_TYPES: ChatAction["action"][] = [
  "data_updated",
  "focus_topic",
  "add_block",
  "remove_block",
  "reorder_blocks",
  "resize_block",
  "apply_template",
  "agent_insight",
  "set_learning_mode",
  "suggest_mode",
];

export function useInitPrompt(courseId: string, setChatOpen: (v: boolean) => void) {
  useEffect(() => {
    const promptKey = `course_init_prompt_${courseId}`;
    const consumedKey = `course_init_prompt_consumed_${courseId}`;
    const initPrompt = localStorage.getItem(promptKey);
    const alreadyConsumed = sessionStorage.getItem(consumedKey) === "true";
    if (initPrompt && !alreadyConsumed) {
      sessionStorage.setItem(consumedKey, "true");
      localStorage.removeItem(promptKey);
      setChatOpen(true);
      const timer = setTimeout(() => {
        void useChatStore.getState().sendMessage(courseId, initPrompt);
      }, 500);
      return () => clearTimeout(timer);
    }
  }, [courseId, setChatOpen]);
}

export function useGreeting(
  courseId: string,
  course: unknown | null,
  handleAction: (action: ChatAction) => void,
) {
  useEffect(() => {
    if (!course) return;
    const greetingKey = `greeting_shown_${courseId}`;
    if (sessionStorage.getItem(greetingKey) === "true") return;

    const chatState = useChatStore.getState();
    const existing = chatState.messagesByCourse[courseId];
    if (existing && existing.length > 0) return;

    sessionStorage.setItem(greetingKey, "true");
    let cancelled = false;

    import("@/lib/api").then(({ getChatGreeting }) => {
      if (cancelled) return;
      getChatGreeting(courseId)
        .then((result) => {
          if (cancelled) return;
          const store = useChatStore.getState();
          const msgs = store.messagesByCourse[courseId] || [];
          if (msgs.length === 0) {
            const greetingMsg = {
              id: `greeting-${courseId}`,
              role: "assistant" as const,
              content: result.greeting,
              timestamp: new Date(),
            };
            useChatStore.setState((s) => ({
              messagesByCourse: { ...s.messagesByCourse, [courseId]: [greetingMsg] },
              messages: s.activeCourseId === courseId ? [greetingMsg] : s.messages,
            }));
          }
          if (result.suggested_actions?.length) {
            for (const action of result.suggested_actions) {
              if (VALID_CHAT_ACTION_TYPES.includes(action.action as ChatAction["action"])) {
                handleAction({
                  action: action.action as ChatAction["action"],
                  value: action.value,
                  extra: action.extra,
                });
              }
            }
          }
        })
        .catch(() => {
          if (cancelled) return;
          const welcome = (course as { metadata?: Record<string, unknown> }).metadata
            ?.welcome_message as string | undefined;
          if (!welcome) return;
          const store = useChatStore.getState();
          const msgs = store.messagesByCourse[courseId] || [];
          if (msgs.length === 0) {
            const welcomeMsg = {
              id: `welcome-${courseId}`,
              role: "assistant" as const,
              content: welcome,
              timestamp: new Date(),
            };
            useChatStore.setState((s) => ({
              messagesByCourse: { ...s.messagesByCourse, [courseId]: [welcomeMsg] },
              messages: s.activeCourseId === courseId ? [welcomeMsg] : s.messages,
            }));
          }
        });
    });
    return () => { cancelled = true; };
  }, [course, courseId, handleAction]);
}
