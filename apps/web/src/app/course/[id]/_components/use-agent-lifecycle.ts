"use client";

import { useEffect } from "react";
import { useWorkspaceStore } from "@/store/workspace";
import { useChatStore } from "@/store/chat";
import type { LearningMode } from "@/lib/block-system/types";
import type { ChatAction } from "@/lib/api";
import { updateUnlockContext } from "@/lib/block-system/feature-unlock";
import { useT, useTF } from "@/lib/i18n-context";

export function useModeEvaluator(
  courseId: string,
  course: unknown | null,
  aiActionsEnabled: boolean,
  queueModeSuggestion: (payload: {
    suggestedMode: LearningMode;
    reason: string;
    approvalCta: string;
    cooldownKey: string;
    signals?: string[];
  }) => boolean,
) {
  const t = useT();
  const tf = useTF();

  useEffect(() => {
    if (!course || !aiActionsEnabled) return;
    const evalKey = `agent_mode_eval_${courseId}`;
    if (sessionStorage.getItem(evalKey) === "true") return;
    sessionStorage.setItem(evalKey, "true");

    const currentMode = useWorkspaceStore.getState().spaceLayout.mode as LearningMode | undefined;
    if (!currentMode) return;

    import("@/lib/api/progress").then(async ({ listStudyGoals, getCourseProgress }) => {
      const goals = await listStudyGoals(courseId, "active").catch(() => []);
      const now = Date.now();
      const deadlines = goals
        .filter((g) => g.target_date)
        .map((g) => ({
          goal: g,
          daysLeft: Math.ceil((new Date(g.target_date!).getTime() - now) / (1000 * 60 * 60 * 24)),
        }));

      if (deadlines.length > 0) {
        updateUnlockContext(courseId, { hasDeadline: true });
      }

      const upcoming = deadlines
        .filter((d) => d.daysLeft >= 0 && d.daysLeft <= 7)
        .sort((a, b) => a.daysLeft - b.daysLeft)[0];
      const allDeadlinesPassed = deadlines.length > 0 && deadlines.every((d) => d.daysLeft < 0);

      const progress = await getCourseProgress(courseId).catch(() => null);
      const mastery = progress ? Math.round((progress.average_mastery ?? 0) * 100) : null;
      const totalAttempts = progress ? progress.mastered + progress.reviewed + progress.in_progress : 0;
      const errorRatePct =
        progress && totalAttempts > 10
          ? Math.round((progress.in_progress / totalAttempts) * 100)
          : null;

      if (currentMode === "exam_prep" && allDeadlinesPassed) {
        queueModeSuggestion({
          suggestedMode: "maintenance",
          reason: t("course.modeSuggestion.examPassed"),
          approvalCta: t("course.modeSuggestion.switchMaintenance"),
          cooldownKey: "exam_passed",
          signals: [t("course.modeSuggestion.signal.deadlinesPassed")],
        });
        return;
      }

      if (currentMode === "course_following" || currentMode === "self_paced") {
        if (upcoming && errorRatePct != null && errorRatePct > 40) {
          queueModeSuggestion({
            suggestedMode: "exam_prep",
            reason: tf("course.modeSuggestion.errorRateDetailed", {
              rate: errorRatePct,
              days: upcoming.daysLeft,
            }),
            approvalCta: t("course.modeSuggestion.switchExamPrep"),
            cooldownKey: "error_rate",
            signals: [
              tf("course.modeSuggestion.signal.errorRate", { rate: errorRatePct }),
              tf("course.modeSuggestion.signal.deadline", { days: upcoming.daysLeft }),
            ],
          });
          return;
        }

        if (upcoming) {
          queueModeSuggestion({
            suggestedMode: "exam_prep",
            reason: tf("course.modeSuggestion.deadline", {
              title: upcoming.goal.title,
              days: upcoming.daysLeft,
            }),
            approvalCta: t("course.modeSuggestion.switchExamPrep"),
            cooldownKey: "deadline",
            signals: [tf("course.modeSuggestion.signal.deadline", { days: upcoming.daysLeft })],
          });
          return;
        }

        if (mastery != null && mastery >= 85) {
          queueModeSuggestion({
            suggestedMode: "maintenance",
            reason: tf("course.modeSuggestion.mastery", { mastery }),
            approvalCta: t("course.modeSuggestion.switchMaintenance"),
            cooldownKey: "mastery",
            signals: [tf("course.modeSuggestion.signal.mastery", { mastery })],
          });
        }
      }
    }).catch((e) => console.error("[Course] mode evaluator failed:", e));
  }, [course, courseId, aiActionsEnabled, t, tf, queueModeSuggestion]);
}

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

    import("@/lib/api/chat").then(({ getChatGreeting }) => {
      getChatGreeting(courseId)
        .then((result: { greeting: string; course_name: string; suggested_actions?: ChatAction[] }) => {
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
              handleAction(action);
            }
          }
        })
        .catch(() => {
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
  }, [course, courseId, handleAction]);
}
