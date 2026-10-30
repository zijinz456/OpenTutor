import { create } from "zustand";
import { getCourseProgress, getWrongAnswerStats, listStudyGoals } from "@/lib/api";
import type { BlockType, LearningMode } from "./types";

/**
 * Feature unlock conditions.
 *
 * The signals are derived from server data (course progress, wrong-answer
 * stats, study goals, content tree) — never from frontend counters — so the
 * same unlock state is visible on every device.
 */

/** Server-derived per-course signals. */
export interface UnlockSignals {
  /** Concepts with any learning activity (mastered + reviewed + in progress). */
  practicedConcepts: number;
  /** Whether the learner has at least one recorded wrong answer. */
  hasWrongAnswer: boolean;
  /** Whether any active study goal has a target date. */
  hasDeadline: boolean;
}

export interface UnlockContext extends UnlockSignals {
  /** Number of top-level content nodes (source documents) in this course. */
  sourceDocCount: number;
  /** Total number of courses the user has. */
  totalCourses: number;
  /** Current learning mode of this course. */
  mode?: LearningMode;
}

export const EMPTY_UNLOCK_SIGNALS: UnlockSignals = {
  practicedConcepts: 0,
  hasWrongAnswer: false,
  hasDeadline: false,
};

/** Block types that are always available regardless of unlock state. */
const ALWAYS_AVAILABLE: BlockType[] = [
  "notes", "quiz", "flashcards", "chapter_list", "review", "progress", "summary", "agent_insight",
];

const KNOWLEDGE_GRAPH_MIN_DOCS = 3;
const FORECAST_MIN_PRACTICED = 5;

/**
 * Check if a block type is unlocked given the current context.
 * Returns { unlocked, reason, unlockHint } where reason explains the unlock condition.
 */
export function isBlockUnlocked(
  type: BlockType,
  ctx: UnlockContext,
): { unlocked: boolean; reason?: string; unlockHint?: string } {
  if (ALWAYS_AVAILABLE.includes(type)) {
    return { unlocked: true };
  }

  switch (type) {
    case "knowledge_graph":
      return ctx.sourceDocCount >= KNOWLEDGE_GRAPH_MIN_DOCS
        ? { unlocked: true }
        : {
          unlocked: false,
          reason: `Unlocks after uploading ${KNOWLEDGE_GRAPH_MIN_DOCS}+ source documents`,
          unlockHint: `${ctx.sourceDocCount}/${KNOWLEDGE_GRAPH_MIN_DOCS} documents`,
        };

    case "plan":
      return ctx.hasDeadline || ctx.mode === "course_following"
        ? { unlocked: true }
        : {
          unlocked: false,
          reason: "Unlocks after setting a deadline or enabling Course Following mode",
          unlockHint: "Set a deadline to unlock",
        };

    case "forecast":
      return ctx.practicedConcepts >= FORECAST_MIN_PRACTICED
        ? { unlocked: true }
        : {
          unlocked: false,
          reason: `Unlocks after practicing ${FORECAST_MIN_PRACTICED}+ concepts`,
          unlockHint: `${ctx.practicedConcepts}/${FORECAST_MIN_PRACTICED} concepts practiced`,
        };

    case "wrong_answers":
      return ctx.hasWrongAnswer
        ? { unlocked: true }
        : {
          unlocked: false,
          reason: "Unlocks after your first incorrect answer",
          unlockHint: "Answer a question incorrectly to unlock",
        };

    default:
      return { unlocked: true };
  }
}

// ── Server-derived signal cache ──

interface UnlockSignalsState {
  byCourse: Record<string, UnlockSignals>;
  setSignals: (courseId: string, signals: UnlockSignals) => void;
}

export const useUnlockSignalsStore = create<UnlockSignalsState>((set) => ({
  byCourse: {},
  setSignals: (courseId, signals) =>
    set((s) => ({ byCourse: { ...s.byCourse, [courseId]: signals } })),
}));

/**
 * Re-fetch the unlock signals for a course from the server.
 * Called by the course layout on mount and after events that change them
 * (a submitted answer, a new goal with a deadline).
 */
export async function refreshUnlockSignals(courseId: string): Promise<UnlockSignals> {
  const [progress, stats, goals] = await Promise.allSettled([
    getCourseProgress(courseId),
    getWrongAnswerStats(courseId),
    listStudyGoals(courseId, "active"),
  ]);

  const previous = useUnlockSignalsStore.getState().byCourse[courseId] ?? EMPTY_UNLOCK_SIGNALS;
  const next: UnlockSignals = {
    practicedConcepts: progress.status === "fulfilled"
      ? (progress.value.mastered ?? 0) + (progress.value.reviewed ?? 0) + (progress.value.in_progress ?? 0)
      : previous.practicedConcepts,
    hasWrongAnswer: stats.status === "fulfilled"
      ? (stats.value.total ?? 0) > 0
      : previous.hasWrongAnswer,
    hasDeadline: goals.status === "fulfilled"
      ? goals.value.some((goal) => Boolean(goal.target_date))
      : previous.hasDeadline,
  };

  useUnlockSignalsStore.getState().setSignals(courseId, next);
  return next;
}

/** Read the cached signals for a course (reactive). */
export function useUnlockSignals(courseId: string): UnlockSignals {
  return useUnlockSignalsStore((s) => s.byCourse[courseId]) ?? EMPTY_UNLOCK_SIGNALS;
}

/** Combine server signals with store-derived context into an UnlockContext. */
export function buildUnlockContext(
  signals: UnlockSignals,
  extra: { sourceDocCount: number; totalCourses: number; mode?: LearningMode },
): UnlockContext {
  return { ...signals, ...extra };
}
