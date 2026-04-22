import { describe, it, expect, beforeEach } from "vitest";
import { useDailySessionStore } from "./daily-session";
import type { DailyPlanCard } from "@/lib/api";

function makeCards(n: number): DailyPlanCard[] {
  return Array.from({ length: n }, (_, i) => ({
    id: `card-${i}`,
    question_type: "multiple_choice",
    question: `Q${i}`,
    options: { a: "A", b: "B" },
    correct_answer: null,
    explanation: null,
    difficulty_layer: 1,
    content_node_id: null,
    problem_metadata: null,
  }));
}

describe("useDailySessionStore", () => {
  beforeEach(() => {
    useDailySessionStore.getState().reset();
  });

  describe("start", () => {
    it("seeds fresh state from fetched cards", () => {
      useDailySessionStore.getState().start(5, makeCards(5));
      const s = useDailySessionStore.getState();
      expect(s.cards).toHaveLength(5);
      expect(s.currentIdx).toBe(0);
      expect(s.answered).toBe(0);
      expect(s.size).toBe(5);
      expect(s.finished).toBe(false);
      expect(s.stats).toEqual({ correct: 0, wrong: 0 });
    });

    it("wipes prior session state when restarting", () => {
      useDailySessionStore.getState().start(1, makeCards(1));
      useDailySessionStore.getState().recordAnswer(true);
      expect(useDailySessionStore.getState().finished).toBe(true);

      useDailySessionStore.getState().start(5, makeCards(5));
      const s = useDailySessionStore.getState();
      expect(s.finished).toBe(false);
      expect(s.answered).toBe(0);
      expect(s.stats.correct).toBe(0);
    });

    it("marks finished immediately when starting with empty pool", () => {
      useDailySessionStore.getState().start(10, []);
      expect(useDailySessionStore.getState().finished).toBe(true);
    });
  });

  describe("recordAnswer", () => {
    it("increments correct stat on correct answer", () => {
      useDailySessionStore.getState().start(5, makeCards(5));
      useDailySessionStore.getState().recordAnswer(true);
      expect(useDailySessionStore.getState().stats).toEqual({ correct: 1, wrong: 0 });
    });

    it("increments wrong stat on incorrect answer", () => {
      useDailySessionStore.getState().start(5, makeCards(5));
      useDailySessionStore.getState().recordAnswer(false);
      expect(useDailySessionStore.getState().stats).toEqual({ correct: 0, wrong: 1 });
    });

    it("does not flip finished until answered hits size", () => {
      useDailySessionStore.getState().start(5, makeCards(5));
      useDailySessionStore.getState().recordAnswer(true);
      useDailySessionStore.getState().recordAnswer(true);
      expect(useDailySessionStore.getState().finished).toBe(false);
    });

    it("flips finished when answered reaches size", () => {
      // Cast: 3 is not in the production `DailySessionSize` union (1 | 5 | 10)
      // but the store logic is size-agnostic and a small size stresses the
      // transition edge with fewer steps. The CTA component is what
      // enforces the allowed trio in the UI surface.
      useDailySessionStore.getState().start(3 as unknown as 5, makeCards(3));
      useDailySessionStore.getState().recordAnswer(true);
      useDailySessionStore.getState().recordAnswer(false);
      useDailySessionStore.getState().recordAnswer(true);
      const s = useDailySessionStore.getState();
      expect(s.finished).toBe(true);
      expect(s.answered).toBe(3);
      expect(s.stats).toEqual({ correct: 2, wrong: 1 });
    });

    it("flips finished when pool is smaller than requested size (partial fill)", () => {
      // Backend returned 2 cards when we asked for 5; session should end
      // after the 2nd answer, not wait for a 3rd card that doesn't exist.
      useDailySessionStore.getState().start(5, makeCards(2));
      useDailySessionStore.getState().recordAnswer(true);
      expect(useDailySessionStore.getState().finished).toBe(false);
      useDailySessionStore.getState().recordAnswer(true);
      expect(useDailySessionStore.getState().finished).toBe(true);
    });
  });

  describe("advance", () => {
    it("moves the cursor forward by one", () => {
      useDailySessionStore.getState().start(5, makeCards(5));
      useDailySessionStore.getState().advance();
      expect(useDailySessionStore.getState().currentIdx).toBe(1);
    });

    it("clamps at the last card", () => {
      useDailySessionStore.getState().start(5, makeCards(3));
      useDailySessionStore.getState().advance();
      useDailySessionStore.getState().advance();
      useDailySessionStore.getState().advance();
      useDailySessionStore.getState().advance();
      expect(useDailySessionStore.getState().currentIdx).toBe(2);
    });

    it("does not go negative when the pool is empty", () => {
      useDailySessionStore.getState().start(5, []);
      useDailySessionStore.getState().advance();
      expect(useDailySessionStore.getState().currentIdx).toBe(0);
    });
  });

  describe("reset", () => {
    it("clears state to initial defaults", () => {
      useDailySessionStore.getState().start(10, makeCards(10));
      useDailySessionStore.getState().recordAnswer(true);
      useDailySessionStore.getState().advance();

      useDailySessionStore.getState().reset();
      const s = useDailySessionStore.getState();
      expect(s.cards).toEqual([]);
      expect(s.currentIdx).toBe(0);
      expect(s.answered).toBe(0);
      expect(s.finished).toBe(false);
      expect(s.stats).toEqual({ correct: 0, wrong: 0 });
    });
  });
});
