import type { BlockType, LearningMode } from "./types";

/**
 * Feature unlock conditions as defined in the PRD.
 * Each condition returns true if the feature should be unlocked.
 */

export interface UnlockContext {
  /** Number of source documents uploaded to this course. */
  sourceDocCount: number;
  /** Total practice attempts across all quizzes. */
  practiceAttempts: number;
  /** Whether the user has ever gotten a wrong answer. */
  hasWrongAnswer: boolean;
  /** Number of learning sessions (visits) for this course. */
  sessionCount: number;
  /** Total number of courses the user has. */
  totalCourses: number;
  /** Current learning mode of this course. */
  mode?: LearningMode;
  /** Whether any deadline has been set. */
  hasDeadline: boolean;
}

/** Block types that are always available regardless of unlock state. */
const ALWAYS_AVAILABLE: BlockType[] = [
  "notes", "quiz", "flashcards", "chapter_list", "review",
];

/**
 * Check if a block type is unlocked given the current context.
 * Returns { unlocked, reason } where reason explains the unlock condition.
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
      return ctx.sourceDocCount >= 3
        ? { unlocked: true }
        : { unlocked: false, reason: "Unlocks after uploading 3+ source documents", unlockHint: `${ctx.sourceDocCount}/3 documents` };

    case "plan":
      return ctx.hasDeadline || ctx.mode === "course_following"
        ? { unlocked: true }
        : { unlocked: false, reason: "Unlocks after setting a deadline or enabling Course Following mode", unlockHint: "Set a deadline to unlock" };

    case "forecast":
      return ctx.practiceAttempts >= 50
        ? { unlocked: true }
        : { unlocked: false, reason: "Unlocks after 50+ practice attempts", unlockHint: `${ctx.practiceAttempts}/50 attempts` };

    case "wrong_answers":
      return ctx.hasWrongAnswer
        ? { unlocked: true }
        : { unlocked: false, reason: "Unlocks after your first incorrect answer", unlockHint: "Answer a question incorrectly to unlock" };

    case "agent_insight":
      return ctx.sessionCount >= 3
        ? { unlocked: true }
        : { unlocked: false, reason: "Unlocks after 3+ learning sessions", unlockHint: `${ctx.sessionCount}/3 sessions` };

    case "progress":
      return { unlocked: true };

    default:
      return { unlocked: true };
  }
}

/**
 * Get the unlock context from localStorage for a given course.
 * This reads persisted stats that the app updates during usage.
 */
export function getUnlockContext(courseId: string, totalCourses: number): UnlockContext {
  if (typeof window === "undefined") {
    return { sourceDocCount: 0, practiceAttempts: 0, hasWrongAnswer: false, sessionCount: 0, totalCourses, hasDeadline: false };
  }

  const key = `opentutor_unlock_${courseId}`;
  try {
    const raw = localStorage.getItem(key);
    if (raw) {
      const data = JSON.parse(raw) as Partial<UnlockContext>;
      return {
        sourceDocCount: data.sourceDocCount ?? 0,
        practiceAttempts: data.practiceAttempts ?? 0,
        hasWrongAnswer: data.hasWrongAnswer ?? false,
        sessionCount: data.sessionCount ?? 0,
        totalCourses,
        mode: data.mode,
        hasDeadline: data.hasDeadline ?? false,
      };
    }
  } catch { /* ignore */ }

  return { sourceDocCount: 0, practiceAttempts: 0, hasWrongAnswer: false, sessionCount: 0, totalCourses, hasDeadline: false };
}

/**
 * Update unlock context in localStorage (partial merge).
 */
export function updateUnlockContext(courseId: string, updates: Partial<UnlockContext>): void {
  if (typeof window === "undefined") return;
  const key = `opentutor_unlock_${courseId}`;
  try {
    const existing = getUnlockContext(courseId, 0);
    const merged = { ...existing, ...updates };
    localStorage.setItem(key, JSON.stringify(merged));
  } catch { /* ignore */ }
}

/**
 * Increment session count for a course (called on page load).
 */
export function incrementSessionCount(courseId: string): void {
  const ctx = getUnlockContext(courseId, 0);
  updateUnlockContext(courseId, { sessionCount: ctx.sessionCount + 1 });
}
