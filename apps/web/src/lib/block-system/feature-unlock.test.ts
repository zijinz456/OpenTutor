import { describe, it, expect, beforeEach } from "vitest";
import {
  isBlockUnlocked,
  getUnlockContext,
  updateUnlockContext,
  incrementSessionCount,
  type UnlockContext,
} from "./feature-unlock";

function makeCtx(overrides: Partial<UnlockContext> = {}): UnlockContext {
  return {
    sourceDocCount: 0,
    practiceAttempts: 0,
    hasWrongAnswer: false,
    sessionCount: 0,
    totalCourses: 1,
    hasDeadline: false,
    ...overrides,
  };
}

describe("isBlockUnlocked", () => {
  it("always unlocks core block types", () => {
    const ctx = makeCtx();
    for (const type of ["notes", "quiz", "flashcards", "chapter_list", "review"] as const) {
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

  it("unlocks forecast after 50+ practice attempts", () => {
    expect(isBlockUnlocked("forecast", makeCtx({ practiceAttempts: 49 })).unlocked).toBe(false);
    expect(isBlockUnlocked("forecast", makeCtx({ practiceAttempts: 50 })).unlocked).toBe(true);
  });

  it("unlocks wrong_answers after first wrong answer", () => {
    expect(isBlockUnlocked("wrong_answers", makeCtx()).unlocked).toBe(false);
    expect(isBlockUnlocked("wrong_answers", makeCtx({ hasWrongAnswer: true })).unlocked).toBe(true);
  });

  it("unlocks agent_insight after 3+ sessions", () => {
    expect(isBlockUnlocked("agent_insight", makeCtx({ sessionCount: 2 })).unlocked).toBe(false);
    expect(isBlockUnlocked("agent_insight", makeCtx({ sessionCount: 3 })).unlocked).toBe(true);
  });

  it("provides unlock hints for locked blocks", () => {
    const result = isBlockUnlocked("knowledge_graph", makeCtx({ sourceDocCount: 1 }));
    expect(result.unlocked).toBe(false);
    expect(result.unlockHint).toContain("1/3");
  });

  it("always unlocks progress", () => {
    const ctx = makeCtx();
    expect(isBlockUnlocked("progress", ctx).unlocked).toBe(true);
  });
});

describe("getUnlockContext / updateUnlockContext", () => {
  beforeEach(() => localStorage.clear());

  it("returns defaults when nothing stored", () => {
    const ctx = getUnlockContext("course-1", 5);
    expect(ctx.sourceDocCount).toBe(0);
    expect(ctx.totalCourses).toBe(5);
  });

  it("persists and reads back updates", () => {
    updateUnlockContext("course-1", { practiceAttempts: 10, hasWrongAnswer: true });
    const ctx = getUnlockContext("course-1", 1);
    expect(ctx.practiceAttempts).toBe(10);
    expect(ctx.hasWrongAnswer).toBe(true);
  });

  it("merges partial updates", () => {
    updateUnlockContext("course-1", { sourceDocCount: 5 });
    updateUnlockContext("course-1", { practiceAttempts: 20 });
    const ctx = getUnlockContext("course-1", 1);
    expect(ctx.sourceDocCount).toBe(5);
    expect(ctx.practiceAttempts).toBe(20);
  });
});

describe("incrementSessionCount", () => {
  beforeEach(() => localStorage.clear());

  it("increments session count by 1", () => {
    incrementSessionCount("course-1");
    incrementSessionCount("course-1");
    const ctx = getUnlockContext("course-1", 1);
    expect(ctx.sessionCount).toBe(2);
  });
});
