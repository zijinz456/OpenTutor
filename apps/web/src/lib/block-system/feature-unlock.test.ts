import { describe, it, expect, beforeEach, vi } from "vitest";

const mockGetCourseProgress = vi.fn();
const mockGetWrongAnswerStats = vi.fn();
const mockListStudyGoals = vi.fn();

vi.mock("@/lib/api", () => ({
  getCourseProgress: (...args: unknown[]) => mockGetCourseProgress(...args),
  getWrongAnswerStats: (...args: unknown[]) => mockGetWrongAnswerStats(...args),
  listStudyGoals: (...args: unknown[]) => mockListStudyGoals(...args),
}));

import {
  isBlockUnlocked,
  buildUnlockContext,
  refreshUnlockSignals,
  useUnlockSignalsStore,
  EMPTY_UNLOCK_SIGNALS,
  type UnlockContext,
} from "./feature-unlock";

function makeCtx(overrides: Partial<UnlockContext> = {}): UnlockContext {
  return {
    sourceDocCount: 0,
    practicedConcepts: 0,
    hasWrongAnswer: false,
    totalCourses: 1,
    hasDeadline: false,
    ...overrides,
  };
}

describe("isBlockUnlocked", () => {
  it("always unlocks core block types", () => {
    const ctx = makeCtx();
    for (const type of ["notes", "quiz", "flashcards", "chapter_list", "review", "progress", "summary", "agent_insight"] as const) {
      expect(isBlockUnlocked(type, ctx).unlocked).toBe(true);
    }
  });

  it("unlocks knowledge_graph after 3+ source docs", () => {
    expect(isBlockUnlocked("knowledge_graph", makeCtx({ sourceDocCount: 2 })).unlocked).toBe(false);
    expect(isBlockUnlocked("knowledge_graph", makeCtx({ sourceDocCount: 3 })).unlocked).toBe(true);
  });

  it("unlocks plan with deadline or course_following mode", () => {
    expect(isBlockUnlocked("plan", makeCtx()).unlocked).toBe(false);
    expect(isBlockUnlocked("plan", makeCtx({ hasDeadline: true })).unlocked).toBe(true);
    expect(isBlockUnlocked("plan", makeCtx({ mode: "course_following" })).unlocked).toBe(true);
  });

  it("unlocks forecast after 5+ practiced concepts", () => {
    expect(isBlockUnlocked("forecast", makeCtx({ practicedConcepts: 4 })).unlocked).toBe(false);
    expect(isBlockUnlocked("forecast", makeCtx({ practicedConcepts: 5 })).unlocked).toBe(true);
  });

  it("unlocks wrong_answers after first wrong answer", () => {
    expect(isBlockUnlocked("wrong_answers", makeCtx()).unlocked).toBe(false);
    expect(isBlockUnlocked("wrong_answers", makeCtx({ hasWrongAnswer: true })).unlocked).toBe(true);
  });

  it("provides unlock hints for locked blocks", () => {
    const result = isBlockUnlocked("knowledge_graph", makeCtx({ sourceDocCount: 1 }));
    expect(result.unlocked).toBe(false);
    expect(result.unlockHint).toContain("1/3");
  });
});

describe("buildUnlockContext", () => {
  it("merges server signals with store-derived context", () => {
    const ctx = buildUnlockContext(
      { practicedConcepts: 7, hasWrongAnswer: true, hasDeadline: false },
      { sourceDocCount: 4, totalCourses: 2, mode: "exam_prep" },
    );
    expect(ctx).toEqual({
      practicedConcepts: 7,
      hasWrongAnswer: true,
      hasDeadline: false,
      sourceDocCount: 4,
      totalCourses: 2,
      mode: "exam_prep",
    });
  });
});

describe("refreshUnlockSignals", () => {
  beforeEach(() => {
    useUnlockSignalsStore.setState({ byCourse: {} });
    mockGetCourseProgress.mockReset();
    mockGetWrongAnswerStats.mockReset();
    mockListStudyGoals.mockReset();
  });

  it("derives signals from server data", async () => {
    mockGetCourseProgress.mockResolvedValue({ mastered: 2, reviewed: 1, in_progress: 3 });
    mockGetWrongAnswerStats.mockResolvedValue({ total: 4 });
    mockListStudyGoals.mockResolvedValue([{ id: "g1", target_date: "2030-01-01" }]);

    const signals = await refreshUnlockSignals("course-1");

    expect(signals).toEqual({ practicedConcepts: 6, hasWrongAnswer: true, hasDeadline: true });
    expect(useUnlockSignalsStore.getState().byCourse["course-1"]).toEqual(signals);
  });

  it("keeps previous values for requests that fail", async () => {
    useUnlockSignalsStore.getState().setSignals("course-1", {
      practicedConcepts: 9,
      hasWrongAnswer: true,
      hasDeadline: true,
    });
    mockGetCourseProgress.mockRejectedValue(new Error("boom"));
    mockGetWrongAnswerStats.mockResolvedValue({ total: 0 });
    mockListStudyGoals.mockRejectedValue(new Error("boom"));

    const signals = await refreshUnlockSignals("course-1");

    expect(signals).toEqual({ practicedConcepts: 9, hasWrongAnswer: false, hasDeadline: true });
  });

  it("falls back to empty signals when nothing is cached", async () => {
    mockGetCourseProgress.mockRejectedValue(new Error("boom"));
    mockGetWrongAnswerStats.mockRejectedValue(new Error("boom"));
    mockListStudyGoals.mockRejectedValue(new Error("boom"));

    const signals = await refreshUnlockSignals("course-2");

    expect(signals).toEqual(EMPTY_UNLOCK_SIGNALS);
  });
});
