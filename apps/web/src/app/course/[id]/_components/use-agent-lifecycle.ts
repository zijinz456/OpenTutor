"use client";

import { useEffect } from "react";
import { useWorkspaceStore } from "@/store/workspace";
import { useChatStore } from "@/store/chat";
import type { LearningMode } from "@/lib/block-system/types";
import type { ChatAction } from "@/lib/api";
import { updateUnlockContext } from "@/lib/block-system/feature-unlock";
import { useT, useTF } from "@/lib/i18n-context";

const MODE_EVAL_TTL_MS = 10 * 60 * 1000;
const MODE_EVAL_RETRY_MS = 5_000;

interface ModeEvalLatchState {
  successAt?: number;
  retryAt?: number;
  fingerprint?: string;
}

interface ModeEvalGoalSnapshot {
  id: string;
  status: string;
  target_date: string | null;
  next_action: string | null;
}

interface ModeEvalProgressSnapshot {
  average_mastery: number;
  mastered: number;
  reviewed: number;
  in_progress: number;
}

function readModeEvalLatch(key: string): ModeEvalLatchState {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as ModeEvalLatchState;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function writeModeEvalLatch(key: string, value: ModeEvalLatchState): void {
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // no-op
  }
}

function buildModeEvalFingerprint(
  currentMode: LearningMode,
  goals: ModeEvalGoalSnapshot[],
  progress: ModeEvalProgressSnapshot | null,
): string {
  const goalsPart = goals
    .map((goal) => `${goal.id}:${goal.status}:${goal.target_date ?? ""}:${goal.next_action ?? ""}`)
    .sort()
    .join("|");
  const progressPart = progress
    ? [
      progress.average_mastery.toFixed(3),
      progress.mastered,
      progress.reviewed,
      progress.in_progress,
    ].join(":")
    : "no_progress";
  return `${currentMode}::${goalsPart}::${progressPart}`;
}

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
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const runEvaluation = async (isRetry = false) => {
      const now = Date.now();
      const latch = readModeEvalLatch(evalKey);
      if (latch.retryAt && now < latch.retryAt) return;

      try {
        const currentMode = useWorkspaceStore.getState().spaceLayout.mode as LearningMode | undefined;
        if (!currentMode) return;

        const { listStudyGoals, getCourseProgress } = await import("@/lib/api");
        const goals = await listStudyGoals(courseId, "active");
        const progress = await getCourseProgress(courseId);
        if (cancelled) return;

        const fingerprint = buildModeEvalFingerprint(
          currentMode,
          goals as unknown as ModeEvalGoalSnapshot[],
          progress as unknown as ModeEvalProgressSnapshot,
        );
        const latestLatch = readModeEvalLatch(evalKey);
        const shouldSkip =
          latestLatch.successAt != null
          && now - latestLatch.successAt < MODE_EVAL_TTL_MS
          && latestLatch.fingerprint === fingerprint;
        if (shouldSkip) return;

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

        const mastery = Math.round((progress.average_mastery ?? 0) * 100);
        const totalAttempts = progress.mastered + progress.reviewed + progress.in_progress;
        const errorRatePct =
          totalAttempts > 10
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
          writeModeEvalLatch(evalKey, { successAt: Date.now(), fingerprint });
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
            writeModeEvalLatch(evalKey, { successAt: Date.now(), fingerprint });
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
            writeModeEvalLatch(evalKey, { successAt: Date.now(), fingerprint });
            return;
          }

          if (mastery >= 85) {
            queueModeSuggestion({
              suggestedMode: "maintenance",
              reason: tf("course.modeSuggestion.mastery", { mastery }),
              approvalCta: t("course.modeSuggestion.switchMaintenance"),
              cooldownKey: "mastery",
              signals: [tf("course.modeSuggestion.signal.mastery", { mastery })],
            });
          }
        }

        writeModeEvalLatch(evalKey, { successAt: Date.now(), fingerprint });
      } catch (e) {
        console.error("[Course] mode evaluator failed:", e);
        writeModeEvalLatch(evalKey, { retryAt: Date.now() + MODE_EVAL_RETRY_MS });
        if (!cancelled && !isRetry) {
          retryTimer = setTimeout(() => {
            void runEvaluation(true);
          }, MODE_EVAL_RETRY_MS);
        }
      }
    };

    void runEvaluation();
    return () => {
      cancelled = true;
      if (retryTimer) {
        clearTimeout(retryTimer);
      }
    };
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
    let cancelled = false;

    import("@/lib/api").then(({ getChatGreeting }) => {
      if (cancelled) return;
      getChatGreeting(courseId)
        .then((result: { greeting: string; course_name: string; suggested_actions?: ChatAction[] }) => {
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
              handleAction(action);
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
