import { describe, it, expect, beforeEach } from "vitest";
import {
  useBrutalSessionStore,
  MAX_ATTEMPTS,
} from "./brutal-session";
import type { BrutalPlanResponse, DailyPlanCard } from "@/lib/api";

function makeCard(
  id: string,
  conceptSlug: string | null = null,
): DailyPlanCard {
  return {
    id,
    question_type: "multiple_choice",
    question: `Q-${id}`,
    options: { a: "A", b: "B" },
    correct_answer: null,
    explanation: null,
    difficulty_layer: 1,
    content_node_id: null,
    problem_metadata: conceptSlug ? { concept_slug: conceptSlug } : null,
  };
}

function makePlan(cards: DailyPlanCard[]): BrutalPlanResponse {
  return {
    cards,
    size: cards.length,
    strategy: "struggle_first",
    warning: null,
  };
}

describe("useBrutalSessionStore", () => {
  beforeEach(() => {
    useBrutalSessionStore.getState().reset();
  });

  it("start initializes queue + resets counters", () => {
    const plan = makePlan([makeCard("a"), makeCard("b"), makeCard("c")]);
    useBrutalSessionStore.getState().start(plan, 30000);
    const s = useBrutalSessionStore.getState();

    expect(s.queue).toHaveLength(3);
    expect(s.mastered.size).toBe(0);
    expect(s.attempts).toEqual({});
    expect(s.currentStreak).toBe(0);
    expect(s.maxStreak).toBe(0);
    expect(s.forceRetired.size).toBe(0);
    expect(s.conceptFailTally).toEqual({});
    expect(s.timeoutMs).toBe(30000);
    expect(s.startedAt).toBeGreaterThan(0);
    expect(s.isFinished()).toBe(false);
    expect(s.currentCard()?.id).toBe("a");
  });

  it("answer correct shifts queue + increments streak", () => {
    const plan = makePlan([makeCard("a"), makeCard("b"), makeCard("c")]);
    useBrutalSessionStore.getState().start(plan, 30000);
    useBrutalSessionStore.getState().answer("a", true);

    const s = useBrutalSessionStore.getState();
    expect(s.mastered.has("a")).toBe(true);
    expect(s.queue).toHaveLength(2);
    expect(s.queue[0].id).toBe("b");
    expect(s.currentStreak).toBe(1);
    expect(s.maxStreak).toBe(1);
    expect(s.progress()).toEqual({ mastered: 1, total: 3 });
  });

  it("answer wrong requeues to tail + resets streak", () => {
    const plan = makePlan([makeCard("a"), makeCard("b"), makeCard("c")]);
    useBrutalSessionStore.getState().start(plan, 30000);
    // Build a streak first so we can observe the reset.
    useBrutalSessionStore.getState().answer("a", true);
    useBrutalSessionStore.getState().answer("b", false);

    const s = useBrutalSessionStore.getState();
    expect(s.queue).toHaveLength(2);
    expect(s.queue[0].id).toBe("c");
    expect(s.queue[1].id).toBe("b"); // requeued to tail
    expect(s.currentStreak).toBe(0);
    expect(s.maxStreak).toBe(1); // preserved from earlier correct
    expect(s.attempts.b).toBe(1);
    expect(s.mastered.has("b")).toBe(false);
  });

  it("10 wrong attempts on same card force-retires", () => {
    const plan = makePlan([makeCard("a", "asyncio"), makeCard("b")]);
    useBrutalSessionStore.getState().start(plan, 30000);

    for (let i = 0; i < MAX_ATTEMPTS; i++) {
      useBrutalSessionStore.getState().answer("a", false);
    }

    const s = useBrutalSessionStore.getState();
    expect(s.forceRetired.has("a")).toBe(true);
    expect(s.mastered.has("a")).toBe(true); // dropped from queue
    expect(s.queue.find((c) => c.id === "a")).toBeUndefined();
    expect(s.attempts.a).toBe(MAX_ATTEMPTS);
    expect(s.conceptFailTally.asyncio).toBe(MAX_ATTEMPTS);
  });

  it("finishes when all mastered", () => {
    const plan = makePlan([makeCard("a"), makeCard("b"), makeCard("c")]);
    useBrutalSessionStore.getState().start(plan, 30000);
    useBrutalSessionStore.getState().answer("a", true);
    useBrutalSessionStore.getState().answer("b", true);
    useBrutalSessionStore.getState().answer("c", true);

    const s = useBrutalSessionStore.getState();
    expect(s.isFinished()).toBe(true);
    expect(s.queue).toHaveLength(0);
    expect(s.mastered.size).toBe(3);
    expect(s.currentStreak).toBe(3);
    expect(s.maxStreak).toBe(3);
  });
});
